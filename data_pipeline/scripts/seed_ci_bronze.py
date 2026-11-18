"""Fill bronze in a throwaway CI database with fixture records, so dbt can be built and tested
without the streaming path (poller -> API -> Kafka -> consumer).

Usage:
  python scripts/seed_ci_bronze.py [--reset] [--edge-cases] [--late-customer]

  (no flag)        Load every xom_source row as one bronze record, shaped exactly as the poller
                   and consumer will write it (same envelope, same payload hash).
  --edge-cases     Add records that exercise silver and gold: a second version of a sales line,
                   a re-sent duplicate, a sample customer and order dated today, and a sales
                   line whose customer has not arrived yet.
  --late-customer  Send that missing customer, to check that gold re-links the line.
  --reset          Drop and recreate the CI database first.

Target: CI_DATABASE_URL (its database name must end in "_ci"). Source: SOURCE_DATABASE_URL.
This script never writes the dev or prod warehouse: in the real pipeline only the bronze
consumer writes bronze, from Kafka.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.envelope import ENTITIES, to_envelope  # noqa: E402
from src.source.seed import ensure_database, same_database  # noqa: E402
from src.warehouse import apply_schema, bronze_row, insert_raw_records  # noqa: E402

log = logging.getLogger("seed_ci_bronze")

LATE_CUSTOMER = {
    "customer_id": "CI-LATE-0001",
    "first_name": "Late",
    "last_name": "Arrival",
    "birth_date": date(1990, 1, 1),
    "marital_status": "S",
    "gender": None,
    "email_address": None,
    "annual_income": None,
    "education_level": None,
    "occupation": None,
    "home_owner": None,
    "is_sample": True,
}


def write_envelopes(conn, envelopes):
    """Insert envelopes into bronze as the consumer would (one partition, offsets continuing
    bronze's). Returns rows actually inserted."""
    start = conn.execute("SELECT coalesce(max(kafka_offset), -1) + 1 FROM bronze.raw_records")
    offset = start.fetchone()[0]
    rows = (bronze_row(env, 0, offset + i) for i, env in enumerate(envelopes))
    with conn.transaction():
        return insert_raw_records(conn, rows)


def history(source_url, collected_at):
    with psycopg.connect(source_url, row_factory=dict_row) as src:
        for entity, (table, _key, _event) in ENTITIES.items():
            query = sql.SQL("SELECT * FROM {} ORDER BY change_seq").format(
                sql.Identifier("e_commerce", table)
            )
            for row in src.execute(query):
                yield to_envelope(entity, row, collected_at)


def edge_cases(source_url, collected_at):
    with psycopg.connect(source_url, row_factory=dict_row) as src:
        line = src.execute("SELECT * FROM e_commerce.sales_line WHERE row_id = 1").fetchone()
        max_row = src.execute("SELECT max(row_id) FROM e_commerce.sales_line").fetchone()["max"]
    # The same record re-sent unchanged: bronze must ignore it.
    yield to_envelope("sales_line", line, collected_at)
    # A changed version of a real record: silver must keep this one.
    yield to_envelope("sales_line", {**line, "profit": line["profit"] - 1}, collected_at)
    # A sample customer with a sample order dated today.
    customer = {**LATE_CUSTOMER, "customer_id": "CI-SAMPLE-0001", "first_name": "Sample"}
    yield to_envelope("customer", customer, collected_at)
    today = datetime.now(UTC).date()
    sample = {
        **line,
        "row_id": max_row + 1,
        "order_id": "CI-SAMPLE-ORDER-1",
        "order_date": today,
        "customer_id": "CI-SAMPLE-0001",
        "is_sample": True,
    }
    yield to_envelope("sales_line", sample, collected_at)
    # A sales line whose customer has not been sent yet (see --late-customer).
    late = {
        **sample,
        "row_id": max_row + 2,
        "order_id": "CI-SAMPLE-ORDER-2",
        "customer_id": LATE_CUSTOMER["customer_id"],
    }
    yield to_envelope("sales_line", late, collected_at)


def main():
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--reset", action="store_true", help="drop and recreate the CI database")
    ap.add_argument("--edge-cases", action="store_true", help="add the edge-case records")
    ap.add_argument("--late-customer", action="store_true", help="send the late customer")
    args = ap.parse_args()

    target = os.environ.get("CI_DATABASE_URL")
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    if not target or not source_url:
        sys.exit("Set CI_DATABASE_URL and SOURCE_DATABASE_URL in the environment or .env.")
    dbname = conninfo_to_dict(target).get("dbname") or ""
    if not dbname.endswith("_ci"):
        sys.exit(f"CI_DATABASE_URL must name a *_ci database, not {dbname!r}.")
    for other in ("DATABASE_URL", "SOURCE_DATABASE_URL"):
        if os.environ.get(other) and same_database(target, os.environ[other]):
            sys.exit(f"CI_DATABASE_URL and {other} name the same database.")

    if args.reset:
        with psycopg.connect(make_conninfo(target, dbname="postgres"), autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname))
            )
        log.info("dropped %s", dbname)
    if ensure_database(target):
        log.info("created %s", dbname)

    collected_at = datetime.now(UTC)
    # Autocommit, so each write_envelopes() call is its own transaction (one consumer batch).
    with psycopg.connect(target, autocommit=True) as conn:
        apply_schema(conn)
        has_rows = conn.execute("SELECT EXISTS (SELECT 1 FROM bronze.raw_records)").fetchone()[0]
        if not has_rows:
            n = write_envelopes(conn, history(source_url, collected_at))
            log.info("history: %s records inserted", f"{n:,}")
        else:
            log.info("history: bronze already has rows, skipped (use --reset to reload)")
        if args.edge_cases:
            n = write_envelopes(conn, edge_cases(source_url, collected_at))
            log.info("edge cases: %d records inserted (5 sent, 1 is a duplicate)", n)
        if args.late_customer:
            n = write_envelopes(conn, [to_envelope("customer", LATE_CUSTOMER, collected_at)])
            log.info("late customer: %d record inserted", n)


if __name__ == "__main__":
    main()
