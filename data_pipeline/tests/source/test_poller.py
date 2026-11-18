"""Source poller: rows become envelopes without the technical columns, reference tables go before
sales lines, the mark moves only after a 202, and a failed send is re-sent on the next cycle.
Unit tests use fakes; one test runs the real reader and offset store against a throwaway database
holding both the source tables and ops.source_offsets."""

import json
import threading
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg
import pytest

from src.source import poller

T = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


class FakeReader:
    def __init__(self, tables):
        self.tables = tables  # entity -> list of row dicts with change_seq

    def read_batch(self, entity, after, limit):
        rows = sorted(
            (r for r in self.tables.get(entity, []) if r["change_seq"] > after),
            key=lambda r: r["change_seq"],
        )
        return rows[:limit]


class FakeOffsets(dict):
    def get(self, entity):
        return super().get(entity, 0)

    def set(self, entity, seq):
        self[entity] = seq


class FakeApi:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.batches = []  # (status, envelopes)

    def __call__(self, envelopes):
        status = self.statuses.pop(0) if self.statuses else 202
        self.batches.append((status, envelopes))
        return status, "{}"


def customer(seq, cid="C-1", **extra):
    return {"customer_id": cid, "gender": None, "is_sample": False, "change_seq": seq, **extra}


def sales_line(seq, row_id, **extra):
    return {
        "row_id": row_id,
        "order_date": date(2023, 10, 2),
        "customer_id": "C-1",
        "sales": 48,
        "is_sample": False,
        "change_seq": seq,
        **extra,
    }


def test_rows_become_envelopes_without_technical_columns():
    reader = FakeReader({"sales_line": [sales_line(7, 1, is_sample=True)]})
    api = FakeApi()
    poller.poll_once(reader, FakeOffsets(), api, 100, clock=lambda: T)
    [(_status, [env])] = api.batches
    assert env["entity"] == "sales_line" and env["record_id"] == "1"
    assert env["is_sample"] is True and env["source_version"] == 7
    assert env["event_at"] == "2023-10-02" and env["collected_at"] == T.isoformat()
    assert "change_seq" not in env["payload"] and "is_sample" not in env["payload"]


def test_reference_tables_are_sent_before_sales_lines():
    # The sales line has the lowest change_seq, yet goes last.
    reader = FakeReader(
        {
            "sales_line": [sales_line(1, 1)],
            "region": [{"region_code": "R1", "is_sample": False, "change_seq": 4}],
            "product": [{"product_code": "P1", "is_sample": False, "change_seq": 3}],
            "customer": [customer(2)],
        }
    )
    api = FakeApi()
    sent = poller.poll_once(reader, FakeOffsets(), api, 100)
    order = [b[1][0]["entity"] for b in api.batches]
    assert order == ["customer", "product", "region", "sales_line"]
    assert sent == {"customer": 1, "product": 1, "region": 1, "sales_line": 1}


def test_a_table_is_drained_in_batches_and_the_mark_follows_each_202():
    reader = FakeReader({"customer": [customer(s, f"C-{s}") for s in range(1, 6)]})
    api, offsets = FakeApi(), FakeOffsets()
    sent = poller.poll_once(reader, offsets, api, 2)
    assert [len(b[1]) for b in api.batches] == [2, 2, 1]
    assert offsets["customer"] == 5 and sent["customer"] == 5
    assert poller.poll_once(reader, offsets, api, 2) == dict.fromkeys(sent, 0), "caught up"


def test_failed_send_keeps_the_mark_and_the_next_cycle_resends():
    reader = FakeReader(
        {"customer": [customer(1), customer(2, "C-2")], "sales_line": [sales_line(3, 1)]}
    )
    api, offsets = FakeApi(503), FakeOffsets()
    with pytest.raises(poller.SendError, match="503"):
        poller.poll_once(reader, offsets, api, 100)
    assert offsets == {}, "no 202, no mark"
    assert len(api.batches) == 1, "sales lines are not sent after a reference table failed"

    poller.poll_once(reader, offsets, api, 100)
    assert [e["record_id"] for e in api.batches[1][1]] == ["C-1", "C-2"], "same rows re-sent"
    assert offsets == {"customer": 2, "sales_line": 3}


def test_a_rejected_batch_is_not_skipped():
    reader = FakeReader({"customer": [customer(1)]})
    api, offsets = FakeApi(400), FakeOffsets()
    with pytest.raises(poller.SendError, match="400"):
        poller.poll_once(reader, offsets, api, 100)
    assert offsets == {}


# --- HTTP sender ------------------------------------------------------------------------------


@pytest.fixture
def http_api():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers["Content-Type"], body))
            status = 202 if body[0]["record_id"] != "fail" else 503
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"accepted": 1}')

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_http_sender_posts_json_and_reports_status(http_api):
    url, received = http_api
    send = poller.http_sender(url + "/")
    assert send([{"record_id": "1"}])[0] == 202
    assert send([{"record_id": "fail"}])[0] == 503
    assert received[0][:2] == ("/api/v1/records", "application/json")


def test_http_sender_unreachable_api_is_a_send_error():
    send = poller.http_sender("http://127.0.0.1:1", timeout=2)
    with pytest.raises(poller.SendError, match="unreachable"):
        send([{"record_id": "1"}])


# --- against Postgres -------------------------------------------------------------------------


def test_reader_and_offsets_against_postgres(scratch_warehouse):
    """Source tables and ops.source_offsets live in the same throwaway database here."""
    with psycopg.connect(scratch_warehouse, autocommit=True) as conn:
        conn.execute((ROOT / "sql" / "source_schema.sql").read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO e_commerce.customer (customer_id, first_name) VALUES ('C-1', 'Ann')"
        )
        conn.execute(
            "INSERT INTO e_commerce.sales_line (row_id, order_id, order_date, customer_id, sales)"
            " VALUES (1, 'O-1', '2023-10-02', 'C-1', 48.00)"
        )
    reader, offsets, api = (
        poller.SourceReader(scratch_warehouse),
        poller.OffsetStore(scratch_warehouse),
        FakeApi(),
    )
    try:
        assert poller.poll_once(reader, offsets, api, 100)["sales_line"] == 1
        line = api.batches[-1][1][0]
        assert line["payload"]["sales"] == 48.0, "numeric arrives as a JSON number"
        assert line["payload"]["order_date"] == "2023-10-02"
        assert set(line["payload"]) == {
            "row_id", "order_id", "order_date", "customer_id", "segment", "region_code",
            "product_code", "quantity", "sales", "discount", "profit",
        }  # fmt: skip

        assert sum(poller.poll_once(reader, offsets, api, 100).values()) == 0, "nothing new"

        with psycopg.connect(scratch_warehouse, autocommit=True) as conn:
            conn.execute("UPDATE e_commerce.customer SET first_name = 'Anna'")
        sent = poller.poll_once(reader, offsets, api, 100)
        assert sent == {"customer": 1, "product": 0, "region": 0, "sales_line": 0}
        changed = api.batches[-1][1][0]
        assert changed["payload"]["first_name"] == "Anna"
        assert changed["source_version"] > line["source_version"], "an update is a new version"
    finally:
        reader.close()
        offsets.close()

    with psycopg.connect(scratch_warehouse) as conn:
        marks = dict(conn.execute("SELECT entity, last_change_seq FROM ops.source_offsets"))
    assert set(marks) == {"customer", "sales_line"}
