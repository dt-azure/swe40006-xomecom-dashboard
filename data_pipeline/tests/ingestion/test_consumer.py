"""Bronze consumer batch logic, against fake Kafka messages (no broker): validation and rejection,
the commit order (database first, then Kafka), rewinding when Postgres is down, and idempotency
(the same batch twice adds no rows) against a throwaway database."""

import json
from datetime import UTC, date, datetime

import psycopg
import pytest

from src.envelope import message_key, to_envelope
from src.ingestion import consumer as c

COLLECTED = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
TOPIC = "raw.ecom_records"


class FakeMessage:
    def __init__(self, partition, offset, value, error=None):
        self._partition, self._offset, self._value, self._error = partition, offset, value, error

    def topic(self):
        return TOPIC

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset

    def value(self):
        return self._value

    def key(self):
        return None

    def error(self):
        return self._error


class FakeKafkaError:
    def __init__(self, text, fatal=False):
        self.text, self._fatal = text, fatal

    def fatal(self):
        return self._fatal

    def __str__(self):
        return self.text


class FakeConsumer:
    def __init__(self, log):
        self.log = log

    def commit(self, offsets, asynchronous):
        assert asynchronous is False, "offsets are committed synchronously"
        self.log.append(("commit", sorted(offsets)))

    def seek(self, tp):
        self.log.append(("seek", tp))


class FakeStore:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail
        self.batches = []

    def write_batch(self, batch, _started_at):
        if self.fail:
            self.log.append(("write failed",))
            raise psycopg.OperationalError("connection refused")
        self.log.append(("write", len(batch.rows), len(batch.rejected)))
        self.batches.append(batch)
        return len(batch.rows), len(batch.rejected)


def make_tp(tp, offset):
    return (tp[0], tp[1], offset)


def envelope(row_id=1, **changes):
    row = {
        "row_id": row_id,
        "order_id": f"ORDER-{row_id}",
        "order_date": date(2023, 10, 2),
        "customer_id": "C-1",
        "quantity": 3,
        "sales": 48.0,
        "discount": 0.0,
        "profit": 19.2,
        "is_sample": False,
        "change_seq": row_id,
    }
    row.update(changes)
    return to_envelope("sales_line", row, COLLECTED)


def message(partition, offset, record):
    value = record if isinstance(record, bytes) else json.dumps(record).encode()
    return FakeMessage(partition, offset, value)


# --- parsing and validation -------------------------------------------------------------------


def test_valid_messages_become_bronze_rows_as_sent():
    batch = c.parse_messages([message(0, 5, envelope(1)), message(1, 9, envelope(2))])
    assert batch.rejected == []
    first = batch.rows[0]
    assert first[:3] == ("xom_ecom", "sales_line", "1")
    assert first[3] == datetime(2023, 10, 2, tzinfo=UTC), "a date-only event_at is UTC midnight"
    assert json.loads(first[7]) == envelope(1)["payload"], "payload stored untouched"
    assert first[6] == 1, "source_version"
    assert (first[9], first[10]) == (0, 5), "Kafka partition and offset"
    assert batch.next_offsets == {(TOPIC, 0): 6, (TOPIC, 1): 10}


def test_bad_messages_are_rejected_with_a_reason_and_do_not_block():
    bad_envelope = envelope(2) | {"entity": "invoice"}
    batch = c.parse_messages(
        [
            message(0, 0, b"{not json"),
            message(0, 1, bad_envelope),
            FakeMessage(0, 2, None),
            message(0, 3, b"\xff\xfe"),
            message(0, 4, envelope(1)),
        ]
    )
    assert len(batch.rows) == 1, "the valid message after the bad ones still loads"
    reasons = [r[1] for r in batch.rejected]
    assert reasons[0].startswith("not valid JSON")
    assert "entity must be one of" in reasons[1]
    assert "empty message" in reasons[2]
    assert reasons[3].startswith("not valid JSON")
    assert [(r[2], r[3]) for r in batch.rejected] == [(0, 0), (0, 1), (0, 2), (0, 3)]
    assert batch.next_offsets == {(TOPIC, 0): 5}, "rejected messages are consumed too"


def test_kafka_error_events_are_skipped_and_fatal_ones_raise():
    batch = c.parse_messages(
        [FakeMessage(0, -1, None, FakeKafkaError("transport")), message(0, 0, envelope(1))]
    )
    assert len(batch.rows) == 1 and batch.rejected == []
    with pytest.raises(RuntimeError, match="fatal"):
        c.parse_messages([FakeMessage(0, -1, None, FakeKafkaError("fenced", fatal=True))])


# --- commit order -----------------------------------------------------------------------------


def test_database_commits_before_kafka_offsets():
    log = []
    msgs = [message(0, 7, envelope(1)), message(0, 8, b"junk"), message(2, 3, envelope(2))]
    result = c.process_batch(FakeConsumer(log), FakeStore(log), msgs, COLLECTED, make_tp)
    assert result.status == "committed"
    assert log == [("write", 2, 1), ("commit", [(TOPIC, 0, 9), (TOPIC, 2, 4)])]


def test_database_down_means_no_commit_and_a_rewind():
    log = []
    msgs = [message(0, 7, envelope(1)), message(0, 8, envelope(2)), message(1, 4, envelope(3))]
    result = c.process_batch(FakeConsumer(log), FakeStore(log, fail=True), msgs, COLLECTED, make_tp)
    assert result.status == "retry"
    assert ("commit",) not in [entry[:1] for entry in log]
    assert log == [("write failed",), ("seek", (TOPIC, 0, 7)), ("seek", (TOPIC, 1, 4))]


def test_a_batch_of_only_error_events_writes_nothing():
    log = []
    msgs = [FakeMessage(0, -1, None, FakeKafkaError("transport"))]
    result = c.process_batch(FakeConsumer(log), FakeStore(log), msgs, COLLECTED, make_tp)
    assert result.status == "empty" and log == []


# --- against Postgres -------------------------------------------------------------------------


def counts(url):
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM bronze.raw_records),"
            " (SELECT count(*) FROM bronze.rejected_records),"
            " (SELECT count(*) FROM ops.pipeline_runs WHERE stage = 'ingest')"
        ).fetchone()


def test_same_batch_twice_adds_no_rows(scratch_warehouse):
    store, log = c.BronzeStore(scratch_warehouse), []
    msgs = [message(0, i, envelope(i)) for i in range(1, 101)] + [message(0, 101, b"junk")]
    try:
        first = c.process_batch(FakeConsumer(log), store, msgs, COLLECTED, make_tp)
        assert (first.loaded, first.duplicates, first.rejected) == (100, 0, 1)
        assert counts(scratch_warehouse)[0] == 100

        again = c.process_batch(FakeConsumer(log), store, msgs, COLLECTED, make_tp)
        assert (again.loaded, again.duplicates) == (0, 100)
        assert counts(scratch_warehouse)[0] == 100, "re-delivery must not duplicate bronze rows"
    finally:
        store.close()

    with psycopg.connect(scratch_warehouse) as conn:
        runs = conn.execute(
            "SELECT status, rows_loaded, rows_rejected FROM ops.pipeline_runs"
            " WHERE stage = 'ingest' ORDER BY run_id"
        ).fetchall()
        assert runs == [("success", 100, 1), ("success", 0, 1)], "one run row per flush window"
        stored = conn.execute(
            "SELECT is_sample, source_version, payload, event_at, kafka_offset"
            " FROM bronze.raw_records WHERE record_id = '7'"
        ).fetchone()
    assert stored == (False, 7, envelope(7)["payload"], datetime(2023, 10, 2, tzinfo=UTC), 7)


def test_a_changed_record_is_a_new_version_even_when_it_changes_back(scratch_warehouse):
    a1 = envelope(1, profit=19.2, change_seq=10)
    b = envelope(1, profit=5.0, change_seq=11)
    a2 = envelope(1, profit=19.2, change_seq=12)  # same payload as a1, later version
    store = c.BronzeStore(scratch_warehouse)
    try:
        msgs = [message(0, i, rec) for i, rec in enumerate([a1, b, a2, a2])]
        c.process_batch(FakeConsumer([]), store, msgs, COLLECTED, make_tp)
    finally:
        store.close()
    with psycopg.connect(scratch_warehouse) as conn:
        versions = conn.execute(
            "SELECT source_version FROM bronze.raw_records ORDER BY id"
        ).fetchall()
    assert versions == [(10,), (11,), (12,)], "A -> B -> A keeps three versions, re-send ignored"
    assert message_key(a1) == message_key(a2), "versions share a key, so Kafka keeps their order"


def test_a_row_postgres_refuses_is_rejected_alone(scratch_warehouse):
    good = c.parse_messages([message(0, 0, envelope(1)), message(0, 1, envelope(2))])
    # Bypass validation to simulate a value only Postgres objects to (\u0000 in jsonb).
    bad = list(good.rows[1])
    bad[7] = json.dumps({"order_id": "A\u0000B"})
    good.rows[1] = tuple(bad)
    store = c.BronzeStore(scratch_warehouse)
    try:
        assert store.write_batch(good, COLLECTED) == (1, 1)
    finally:
        store.close()
    with psycopg.connect(scratch_warehouse) as conn:
        reason = conn.execute("SELECT reason FROM bronze.rejected_records").fetchone()[0]
    assert reason.startswith("refused by Postgres")
    assert counts(scratch_warehouse)[:2] == (1, 1)
