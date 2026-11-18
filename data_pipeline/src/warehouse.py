"""Warehouse helpers shared by the services that write it (bronze consumer, transform runner) and
the CI fixture loader, so every writer puts the same row shape into bronze."""

import json
from pathlib import Path

from src.envelope import parse_time, payload_hash

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
_SCHEMA_LOCK = "xom-ecom:sql/schema.sql"

RAW_COLUMNS = (
    "source",
    "entity",
    "record_id",
    "event_at",
    "collected_at",
    "is_sample",
    "source_version",
    "payload",
    "payload_hash",
    "kafka_partition",
    "kafka_offset",
)
_COLUMN_LIST = ", ".join(RAW_COLUMNS)
_STAGE_DDL = """
CREATE TEMP TABLE incoming_raw (
    source text, entity text, record_id text, event_at timestamptz, collected_at timestamptz,
    is_sample boolean, source_version bigint, payload jsonb, payload_hash text,
    kafka_partition integer, kafka_offset bigint
) ON COMMIT DROP
"""
_INSERT_SQL = f"""
INSERT INTO bronze.raw_records ({_COLUMN_LIST})
SELECT {_COLUMN_LIST} FROM incoming_raw ORDER BY kafka_partition, kafka_offset
ON CONFLICT ON CONSTRAINT uq_raw_records_version DO NOTHING
"""


def apply_schema(conn):
    """Apply sql/schema.sql (idempotent) under an advisory lock, so two services starting at the
    same time do not race on CREATE ... IF NOT EXISTS."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_SCHEMA_LOCK,))
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def bronze_row(envelope, partition, offset):
    """A validated envelope as a bronze.raw_records row (a tuple in RAW_COLUMNS order). Values are
    stored as sent; only the timestamps become datetimes, so Python, not Postgres, decides how
    they parse (naive means UTC)."""
    event_at = envelope["event_at"]
    return (
        envelope["source"],
        envelope["entity"],
        envelope["record_id"],
        parse_time(event_at) if event_at is not None else None,
        parse_time(envelope["collected_at"]),
        envelope["is_sample"],
        envelope.get("source_version"),
        json.dumps(envelope["payload"], ensure_ascii=False),
        payload_hash(envelope["payload"]),
        partition,
        offset,
    )


def insert_raw_records(conn, rows):
    """Insert bronze rows, ignoring versions bronze already holds. Must run inside the caller's
    transaction (the stage table is dropped on commit). Returns the number of rows inserted."""
    rows = list(rows)
    if not rows:
        return 0
    conn.execute(_STAGE_DDL)
    with conn.cursor().copy(f"COPY incoming_raw ({_COLUMN_LIST}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
    inserted = conn.execute(_INSERT_SQL).rowcount
    # Dropped now, not only at commit, so the caller can call this again in the same transaction.
    conn.execute("DROP TABLE incoming_raw")
    return inserted
