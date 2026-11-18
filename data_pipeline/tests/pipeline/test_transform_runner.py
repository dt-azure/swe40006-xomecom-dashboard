"""Transform runner: skips without new rows, advances the watermark only on success, retries
after a failure. Unit tests use an in-memory store and a fake dbt; one test runs the real SQL
against a throwaway database."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import psycopg

from src.pipeline import transform_runner as tr

T0 = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


class FakeStore:
    """In-memory stand-in for RunStore: bronze is a list of ingested_at values."""

    def __init__(self, bronze=()):
        self.bronze = list(bronze)
        self.runs = []  # dicts: run_id, status, watermark, rows, message

    def connect(self):
        return nullcontext(None)

    def close_interrupted(self, _conn):
        stuck = [r for r in self.runs if r["status"] == "running"]
        for r in stuck:
            r["status"] = "failed"
        return len(stuck)

    def last_watermark(self, _conn):
        marks = [r["watermark"] for r in self.runs if r["status"] == "success"]
        return max(marks) if marks else None

    def bronze_high_mark(self, _conn):
        return max(self.bronze) if self.bronze else None

    def count_new(self, _conn, since, until):
        return sum(1 for t in self.bronze if (since is None or t > since) and t <= until)

    def start_run(self, _conn):
        self.runs.append({"run_id": len(self.runs) + 1, "status": "running", "watermark": None})
        return len(self.runs)

    def finish_run(self, _conn, run_id, ok, rows, watermark, message):
        run = self.runs[run_id - 1]
        run.update(
            status="success" if ok else "failed", rows=rows, watermark=watermark, message=message
        )


class FakeDbt:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        ok = self.outcomes.pop(0) if self.outcomes else True
        return tr.DbtResult(ok, "Done. PASS=1" if ok else "Database Error in model x", 0.1)


def test_skips_when_bronze_is_empty():
    store, dbt = FakeStore(), FakeDbt()
    assert tr.run_cycle(store, dbt) == "skipped"
    assert dbt.calls == 0 and store.runs == []


def test_runs_then_skips_until_new_rows_arrive():
    store, dbt = FakeStore([T0, T0 + timedelta(seconds=1)]), FakeDbt()
    assert tr.run_cycle(store, dbt) == "success"
    assert store.runs[-1]["watermark"] == T0 + timedelta(seconds=1)
    assert store.runs[-1]["rows"] == 2

    assert tr.run_cycle(store, dbt) == "skipped"
    assert dbt.calls == 1 and len(store.runs) == 1, "no run row when there is nothing to do"

    store.bronze.append(T0 + timedelta(seconds=5))
    assert tr.run_cycle(store, dbt) == "success"
    assert store.runs[-1]["rows"] == 1
    assert store.runs[-1]["watermark"] == T0 + timedelta(seconds=5)


def test_failure_keeps_the_watermark_and_the_next_tick_retries():
    store, dbt = FakeStore([T0]), FakeDbt(False, True)
    assert tr.run_cycle(store, dbt) == "failed"
    assert store.runs[-1]["status"] == "failed" and store.runs[-1]["watermark"] is None
    assert store.last_watermark(None) is None
    assert "Database Error" in store.runs[-1]["message"]

    assert tr.run_cycle(store, dbt) == "success", "same rows, retried"
    assert dbt.calls == 2 and store.last_watermark(None) == T0


def test_a_run_left_running_is_closed_as_failed():
    store = FakeStore([T0])
    store.start_run(None)  # a previous process died mid-cycle
    assert tr.run_cycle(store, FakeDbt()) == "success"
    assert [r["status"] for r in store.runs] == ["failed", "success"]


def test_dbt_is_pointed_at_database_url():
    env = tr.dbt_env(
        {"DBT_PG_DBNAME": "other", "PATH": "/bin"}, "postgresql://u:pw@db.example:6543/xom", "prod"
    )
    assert env["DBT_PG_HOST"] == "db.example" and env["DBT_PG_PORT"] == "6543"
    assert env["DBT_PG_USER"] == "u" and env["DBT_PG_PASSWORD"] == "pw"
    assert env["DBT_PG_DBNAME"] == "xom" and env["DBT_CI_DBNAME"] == "xom"
    assert env["DBT_TARGET"] == "prod" and env["PATH"] == "/bin"


def test_summary_keeps_the_result_line_and_the_failures():
    output = (
        "\x1b[0m02:26:00  1 of 3 OK created sql table model gold.dim_date ... [OK in 0.1s]\n"
        "02:26:01  2 of 3 PASS not_null_dim_date_date_day ... [PASS in 0.0s]\n"
        "02:26:01  3 of 3 FAIL 2 assert_fct_reconciles_with_silver ... [FAIL 2 in 0.1s]\n"
        "02:26:01  Failure in test assert_fct_reconciles_with_silver (tests/x.sql)\n"
        "02:26:01  Done. PASS=1 WARN=0 ERROR=1 SKIP=0 NO-OP=0 TOTAL=3\n"
    )
    summary = tr.summarize(output).splitlines()
    assert summary[0].startswith("Done. PASS=1")
    assert any("Failure in test assert_fct_reconciles_with_silver" in line for line in summary)
    assert not any("PASS not_null" in line for line in summary)


# --- the real SQL against a throwaway database -----------------------------------------------


def add_bronze_row(url, record_id, ingested_at):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO bronze.raw_records (source, entity, record_id, collected_at, is_sample,"
            " payload, payload_hash, ingested_at)"
            " VALUES ('xom_ecom', 'region', %s, now(), false, '{}', %s, %s)",
            (record_id, record_id, ingested_at),
        )


def test_cycle_against_postgres(scratch_warehouse):
    store, dbt = tr.RunStore(scratch_warehouse), FakeDbt(False, True)
    assert tr.run_cycle(store, dbt) == "skipped"

    add_bronze_row(scratch_warehouse, "R1", T0)
    add_bronze_row(scratch_warehouse, "R2", T0 + timedelta(seconds=1))
    assert tr.run_cycle(store, dbt) == "failed"
    assert tr.run_cycle(store, dbt) == "success"
    assert tr.run_cycle(store, dbt) == "skipped"

    with psycopg.connect(scratch_warehouse) as conn:
        runs = conn.execute(
            "SELECT status, rows_loaded, watermark, finished_at IS NOT NULL"
            " FROM ops.pipeline_runs WHERE stage = 'transform' ORDER BY run_id"
        ).fetchall()
    assert runs == [
        ("failed", 2, None, True),
        ("success", 2, T0 + timedelta(seconds=1), True),
    ]
