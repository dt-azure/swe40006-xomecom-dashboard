"""Transform runner: run `dbt build` when bronze has rows the last successful build has not seen.

Usage:
  python -m src.pipeline.transform_runner          # loop every TRANSFORM_INTERVAL_SECONDS
  python -m src.pipeline.transform_runner --once   # one cycle, then exit (0 = ok or nothing to do)

One process, one loop, no overlap. Each cycle:
  1. Close any transform run left 'running' (a previous process stopped mid-cycle).
  2. Read the watermark: the highest bronze ingested_at covered by the last successful transform.
  3. If bronze has nothing newer, do nothing (no run row is written).
  4. Otherwise record a 'running' row, run `dbt build`, and finish the row as 'success' with the
     new watermark, or 'failed' with the error and no watermark. A failed cycle is retried on the
     next tick, which is safe: the models are incremental and bronze inserts are idempotent.

The new watermark is bronze's max(ingested_at) read *before* dbt starts, so rows that land during
the build trigger the next cycle. The single bronze consumer commits batches one after another,
so ingested_at grows in commit order and `ingested_at > watermark` sees every new row.

dbt always builds the database named in DATABASE_URL (the runner sets DBT_PG_* from it), so the
watermark and the tables it describes can never live in different databases.
"""

import argparse
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

from src.warehouse import apply_schema

ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = ROOT / "dbt"
DBT_TIMEOUT_SECONDS = 600  # a cycle should take seconds; this only stops a hung build
MESSAGE_LIMIT = 2000

log = logging.getLogger("transform_runner")


@dataclass
class DbtResult:
    ok: bool
    summary: str
    seconds: float


class RunStore:
    """The runner's reads and writes in the warehouse: bronze high-water mark, ops.pipeline_runs."""

    def __init__(self, url):
        self.url = url

    @contextmanager
    def connect(self):
        with psycopg.connect(self.url, autocommit=True, connect_timeout=5) as conn:
            yield conn

    def close_interrupted(self, conn):
        cur = conn.execute(
            "UPDATE ops.pipeline_runs SET status = 'failed', finished_at = now(),"
            " message = 'interrupted: the runner stopped before the cycle finished'"
            " WHERE stage = 'transform' AND status = 'running'"
        )
        return cur.rowcount

    def last_watermark(self, conn):
        return conn.execute(
            "SELECT max(watermark) FROM ops.pipeline_runs"
            " WHERE stage = 'transform' AND status = 'success'"
        ).fetchone()[0]

    def bronze_high_mark(self, conn):
        return conn.execute("SELECT max(ingested_at) FROM bronze.raw_records").fetchone()[0]

    def count_new(self, conn, since, until):
        return conn.execute(
            "SELECT count(*) FROM bronze.raw_records"
            " WHERE ingested_at > coalesce(%s, '-infinity'::timestamptz) AND ingested_at <= %s",
            (since, until),
        ).fetchone()[0]

    def start_run(self, conn):
        return conn.execute(
            "INSERT INTO ops.pipeline_runs (stage, status) VALUES ('transform', 'running')"
            " RETURNING run_id"
        ).fetchone()[0]

    def finish_run(self, conn, run_id, ok, rows, watermark, message):
        conn.execute(
            "UPDATE ops.pipeline_runs SET status = %s, finished_at = now(), rows_loaded = %s,"
            " watermark = %s, message = %s WHERE run_id = %s",
            ("success" if ok else "failed", rows, watermark, message[:MESSAGE_LIMIT], run_id),
        )


def run_cycle(store, run_dbt):
    """One cycle. Returns 'skipped', 'success' or 'failed'."""
    with store.connect() as conn:
        if n := store.close_interrupted(conn):
            log.warning("closed %d interrupted transform run(s) as failed", n)
        watermark = store.last_watermark(conn)
        high = store.bronze_high_mark(conn)
        if high is None or (watermark is not None and high <= watermark):
            log.debug("no new bronze rows (watermark %s)", watermark)
            return "skipped"
        new_rows = store.count_new(conn, watermark, high)
        run_id = store.start_run(conn)

    log.info("run %d: %d new bronze rows since %s, running dbt build", run_id, new_rows, watermark)
    result = run_dbt()

    with store.connect() as conn:
        store.finish_run(
            conn, run_id, result.ok, new_rows, high if result.ok else None, result.summary
        )
    if result.ok:
        log.info(
            "run %d: success in %.1fs, watermark %s. %s",
            run_id,
            result.seconds,
            high,
            result.summary.splitlines()[0] if result.summary else "",
        )
        return "success"
    log.error(
        "run %d: FAILED in %.1fs; retrying next tick.\n%s", run_id, result.seconds, result.summary
    )
    return "failed"


def dbt_env(base_env, database_url, target):
    """Environment for the dbt subprocess: the profile's DBT_PG_* taken from DATABASE_URL."""
    params = conninfo_to_dict(database_url)
    env = dict(base_env)
    env.update(
        DBT_TARGET=target,
        DBT_PG_HOST=params.get("host") or "localhost",
        DBT_PG_PORT=str(params.get("port") or 5432),
        DBT_PG_USER=params.get("user") or "",
        DBT_PG_PASSWORD=params.get("password") or "",
        DBT_PG_DBNAME=params["dbname"],
        DBT_CI_DBNAME=params["dbname"],
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
    )
    return env


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP = re.compile(r"^\d{2}:\d{2}:\d{2}\s+")
_PROBLEM = re.compile(r"\b(Error|ERROR|Failure|FAIL|WARN)\b")


def summarize(output):
    """The 'Done. PASS=..' line first, then the lines that name a failure (at most 20)."""
    lines = [_TIMESTAMP.sub("", _ANSI.sub("", raw)).strip() for raw in output.splitlines()]
    lines = [line for line in lines if line]
    done = [line for line in lines if line.startswith("Done.")]
    problems = [
        line
        for line in lines
        if _PROBLEM.search(line) and not line.startswith("Done.") and " PASS " not in line
    ]
    picked = done[-1:] + problems[:20]
    if not picked:
        picked = lines[-10:]
    return "\n".join(picked)


def dbt_executable():
    beside_python = Path(sys.executable).with_name("dbt")
    return str(beside_python) if beside_python.exists() else "dbt"


def run_dbt_build(database_url, target, timeout=DBT_TIMEOUT_SECONDS):
    cmd = [
        dbt_executable(),
        "build",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        "--log-path",
        str(DBT_DIR / "logs"),
        "--no-use-colors",
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=DBT_DIR,
            env=dbt_env(os.environ, database_url, target),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DbtResult(False, f"dbt build timed out after {timeout}s", time.monotonic() - t0)
    except OSError as e:
        return DbtResult(False, f"could not start dbt: {e}", time.monotonic() - t0)
    output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    return DbtResult(proc.returncode == 0, summarize(output), time.monotonic() - t0)


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--once", action="store_true", help="run one cycle, then exit")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL in the environment or .env.")
    target = os.environ.get("DBT_TARGET", "dev")
    interval = float(os.environ.get("TRANSFORM_INTERVAL_SECONDS", "30"))
    store = RunStore(url)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    log.info(
        "transform runner: target %s, database %s, every %ss%s",
        target,
        conninfo_to_dict(url).get("dbname"),
        f"{interval:g}",
        " (once)" if args.once else "",
    )
    schema_ready = False
    while not stop.is_set():
        started = time.monotonic()
        outcome = "error"
        try:
            if not schema_ready:
                with store.connect() as conn:
                    apply_schema(conn)
                schema_ready = True
            outcome = run_cycle(store, lambda: run_dbt_build(url, target))
        except psycopg.Error as e:
            log.warning("warehouse unavailable, retrying next tick: %s", str(e).strip())
        if args.once:
            sys.exit(0 if outcome in ("skipped", "success") else 1)
        stop.wait(max(0.0, interval - (time.monotonic() - started)))
    log.info("transform runner stopped")


if __name__ == "__main__":
    main()
