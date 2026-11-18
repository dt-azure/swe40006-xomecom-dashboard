"""End-to-end availability checks against the running compose stack (postgres, kafka, api,
consumer, poller, transform-runner). Skipped unless E2E=1.

  docker compose up -d --build
  E2E=1 pytest tests/e2e -v

They check that each service answers, then follow the history through the whole path: xom_source
-> poller -> API -> Kafka -> consumer -> bronze -> dbt -> gold. The waits allow for the poller's
first run (all history); E2E_TIMEOUT_SECONDS (default 600) caps each one.

Read-only except for one deliberate re-send of an existing, unchanged source record (which bronze
must ignore). Nothing is written to xom_source and no new record reaches bronze or gold.

Settings: DATABASE_URL, SOURCE_DATABASE_URL and KAFKA_BOOTSTRAP_SERVERS as in .env; the API at
E2E_API_URL, else API_URL, else http://localhost:5001.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from src.envelope import ENTITIES, to_envelope
from src.source.seed import read_manifest

pytestmark = pytest.mark.skipif(os.environ.get("E2E") != "1", reason="set E2E=1 to run")

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = float(os.environ.get("E2E_TIMEOUT_SECONDS", "600"))
TOPIC = os.environ.get("KAFKA_TOPIC", "raw.ecom_records")
UPSTREAM = {"customer": "customer", "product": "product", "region": "region"}
UPSTREAM["sales_line"] = "ecom_sales"


def api_url():
    return (
        os.environ.get("E2E_API_URL") or os.environ.get("API_URL") or "http://localhost:5001"
    ).rstrip("/")


def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        api_url() + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def warehouse():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)


def source_db():
    return psycopg.connect(os.environ["SOURCE_DATABASE_URL"], connect_timeout=5)


def wait_for(what, check, timeout=TIMEOUT, every=3.0):
    """Poll check() until it returns a truthy value; fail with the last value seen."""
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        last = check()
        if last is True or (last and not isinstance(last, tuple | list | dict)):
            return last
        time.sleep(every)
    pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}; last state: {last}")


def source_state():
    """{entity: (rows, max change_seq)} in xom_source."""
    with source_db() as conn:
        out = {}
        for entity, (table, _key, _event) in ENTITIES.items():
            out[entity] = conn.execute(
                f"SELECT count(*), max(change_seq) FROM e_commerce.{table}"
            ).fetchone()
        return out


def bronze_state():
    """{entity: (distinct records, max source_version, non-sample distinct records)}."""
    with warehouse() as conn:
        rows = conn.execute(
            "SELECT entity, count(DISTINCT record_id), max(source_version),"
            " count(DISTINCT record_id) FILTER (WHERE NOT is_sample)"
            " FROM bronze.raw_records GROUP BY entity"
        ).fetchall()
    return {r[0]: tuple(r[1:]) for r in rows}


def consumer_lag():
    """Total messages the bronze-loader group has not committed yet (None if unknown)."""
    from confluent_kafka import Consumer, TopicPartition

    c = Consumer(
        {
            "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            "group.id": "bronze-loader",
            "enable.auto.commit": False,
        }
    )
    try:
        meta = c.list_topics(TOPIC, timeout=10)
        parts = [TopicPartition(TOPIC, p) for p in meta.topics[TOPIC].partitions]
        committed = c.committed(parts, timeout=10)
        lag = 0
        for tp in committed:
            _low, high = c.get_watermark_offsets(tp, timeout=10)
            lag += high - (tp.offset if tp.offset >= 0 else 0)
        return lag
    finally:
        c.close()


# --- 1. every service answers -----------------------------------------------------------------


def test_api_is_up():
    status, body = http("GET", "/health")
    assert status == 200 and body["status"] == "ok"
    status, body = http("GET", "/api/v1/sources")
    assert status == 200 and body["sources"][0]["source"] == "xom_ecom", (
        "the API answering is an old build without the record endpoints"
    )


def test_kafka_is_up_with_the_topic():
    from confluent_kafka.admin import AdminClient

    admin = AdminClient(
        {"bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")}
    )
    topics = admin.list_topics(timeout=10).topics
    assert TOPIC in topics, f"topic {TOPIC} missing (kafka-init did not run?)"
    assert len(topics[TOPIC].partitions) >= 1


def test_warehouse_and_source_are_up():
    with warehouse() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables"
                " WHERE table_schema IN ('bronze', 'ops')"
            )
        }
        assert {
            "bronze.raw_records",
            "bronze.rejected_records",
            "ops.pipeline_runs",
            "ops.source_offsets",
        } <= tables
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'bronze' AND table_name = 'raw_records'"
            )
        }
        assert "source_version" in cols, "bronze schema not upgraded (consumer not restarted?)"
    assert all(n > 0 for n, _ in source_state().values()), "xom_source is not seeded"


def test_api_rejects_a_bad_envelope_without_publishing():
    status, body = http("POST", "/api/v1/records", {"source": "xom_ecom", "entity": "invoice"})
    assert status == 400 and body["error"] == "Bad Request"


# --- 2. history flows through: xom_source -> poller -> API -> Kafka -> consumer -> bronze -----


def test_history_reaches_bronze():
    expected = source_state()

    def caught_up():
        got = bronze_state()
        behind = {
            e: (got.get(e, (0, None))[:2], expected[e])
            for e in ENTITIES
            if got.get(e, (0, None))[:2] != expected[e]
        }
        return True if not behind else behind

    wait_for("bronze to hold every xom_source record at its latest version", caught_up)


def test_bronze_matches_the_manifest():
    """Step 6's acceptance check: non-sample records in bronze == manifest.csv row counts."""
    manifest = read_manifest(ROOT / "data" / "xomdata" / "manifest.csv")
    got = bronze_state()
    assert {e: got[e][2] for e in ENTITIES} == {e: manifest[UPSTREAM[e]] for e in ENTITIES}


def test_poller_marks_are_at_the_source_head():
    expected = source_state()
    with warehouse() as conn:
        marks = dict(
            conn.execute(
                "SELECT entity, last_change_seq FROM ops.source_offsets WHERE source = 'xom_ecom'"
            ).fetchall()
        )
    assert marks == {e: expected[e][1] for e in ENTITIES}


def test_consumer_has_no_lag_and_logged_its_batches():
    wait_for("the bronze-loader group to catch up", lambda: consumer_lag() == 0, timeout=120)
    with warehouse() as conn:
        n, failed = conn.execute(
            "SELECT count(*) FILTER (WHERE status = 'success'),"
            " count(*) FILTER (WHERE status <> 'success')"
            " FROM ops.pipeline_runs WHERE stage = 'ingest'"
        ).fetchone()
        rejected = conn.execute("SELECT count(*) FROM bronze.rejected_records").fetchone()[0]
    assert n > 0 and failed == 0
    assert rejected == 0, "history should arrive without a single rejected message"


def test_a_resent_record_is_published_but_not_duplicated():
    with source_db() as src:
        src.row_factory = dict_row
        row = src.execute("SELECT * FROM e_commerce.sales_line ORDER BY row_id LIMIT 1").fetchone()
    env = to_envelope("sales_line", row, datetime.now(UTC))
    with warehouse() as conn:
        before = conn.execute(
            "SELECT count(*) FROM bronze.raw_records WHERE entity = 'sales_line'"
            " AND record_id = %s",
            (env["record_id"],),
        ).fetchone()[0]
    assert before >= 1

    status, body = http("POST", "/api/v1/records", env)
    assert status == 202 and body == {"accepted": 1}
    wait_for("the consumer to take the re-sent record", lambda: consumer_lag() == 0, timeout=60)
    with warehouse() as conn:
        after = conn.execute(
            "SELECT count(*) FROM bronze.raw_records WHERE entity = 'sales_line'"
            " AND record_id = %s",
            (env["record_id"],),
        ).fetchone()[0]
    assert after == before, "an identical re-send must not add a bronze row"


def test_api_serves_bronze_records():
    status, body = http("GET", "/api/v1/records?source=xom_ecom&entity=region&page_size=5")
    assert status == 200
    assert body["total"] == source_state()["region"][0]
    assert len(body["records"]) == 5 and body["next_page"] == 2


# --- 3. the transform runner turns it into gold -----------------------------------------------


def test_transform_covers_bronze_and_gold_reconciles_with_the_source():
    def transformed():
        with warehouse() as conn:
            mark, high = conn.execute(
                "SELECT (SELECT max(watermark) FROM ops.pipeline_runs"
                "        WHERE stage = 'transform' AND status = 'success'),"
                " (SELECT max(ingested_at) FROM bronze.raw_records)"
            ).fetchone()
            last = conn.execute(
                "SELECT status, left(message, 300) FROM ops.pipeline_runs"
                " WHERE stage = 'transform' ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        return True if mark is not None and mark >= high else ("watermark", mark, high, last)

    wait_for("a successful transform covering all of bronze", transformed)

    with source_db() as src:
        want = src.execute(
            "SELECT count(*), sum(sales), sum(profit) FROM e_commerce.sales_line"
            " WHERE NOT is_sample"
        ).fetchone()
    with warehouse() as conn:
        got = conn.execute(
            "SELECT count(*), sum(sales), sum(profit) FROM gold.fct_sales_lines WHERE NOT is_sample"
        ).fetchone()
        failed_after = conn.execute(
            "SELECT count(*) FROM ops.pipeline_runs WHERE stage = 'transform'"
            " AND status = 'failed' AND run_id > (SELECT max(run_id) FROM ops.pipeline_runs"
            "   WHERE stage = 'transform' AND status = 'success')"
        ).fetchone()[0]
    assert got == want, "gold.fct_sales_lines must reconcile with xom_source"
    assert failed_after == 0
