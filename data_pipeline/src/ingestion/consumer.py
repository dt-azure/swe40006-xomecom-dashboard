"""Bronze consumer: stream records from Kafka (raw.ecom_records) into bronze.raw_records.

Usage:
  python -m src.ingestion.consumer

Loop, one micro-batch at a time:
  1. Take up to CONSUMER_BATCH_SIZE messages, or whatever arrived within CONSUMER_FLUSH_SECONDS.
  2. Parse and validate each one (the same envelope check as the API). A message that fails is
     written to bronze.rejected_records with the reason; it never blocks the partition.
  3. In ONE database transaction: insert the valid records (ON CONFLICT DO NOTHING, so a
     re-delivered message adds nothing), the rejected ones, and an ops.pipeline_runs row
     (stage 'ingest').
  4. Commit the database, THEN commit the Kafka offsets. The other order could lose records: a
     crash between the two would leave offsets committed for rows that never landed.

If Postgres is unavailable, nothing is committed to Kafka: the consumer rewinds to the batch's
first offsets, backs off and tries again; the records stay in Kafka. A row that Postgres refuses
because of its data (rare: the envelope check catches what it can) is rejected on its own, so the
rest of the batch still lands.

SIGTERM or Ctrl+C: the current batch is finished and committed, then the consumer closes.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

from src.envelope import validate
from src.warehouse import apply_schema, bronze_row, insert_raw_records

log = logging.getLogger("bronze_consumer")

GROUP_ID = "bronze-loader"
MAX_BACKOFF_SECONDS = 30.0
RAW_VALUE_LIMIT = 100_000  # characters of a rejected message kept in bronze.rejected_records


@dataclass
class Batch:
    """One micro-batch, parsed. `next_offsets` / `first_offsets` are keyed by (topic, partition)."""

    rows: list = field(default_factory=list)  # bronze_row tuples
    rejected: list = field(default_factory=list)  # (raw_value, reason, partition, offset)
    next_offsets: dict = field(default_factory=dict)
    first_offsets: dict = field(default_factory=dict)

    @property
    def size(self):
        return len(self.rows) + len(self.rejected)


@dataclass
class BatchResult:
    status: str  # 'committed', 'retry' or 'empty'
    loaded: int = 0
    duplicates: int = 0
    rejected: int = 0
    offsets: dict = field(default_factory=dict)  # (topic, partition) -> next offset


def _raw_text(value):
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text.replace("\x00", "\\u0000")[:RAW_VALUE_LIMIT]


def parse_messages(messages):
    """Sort Kafka messages into bronze rows and rejects; error events are logged and skipped."""
    batch = Batch()
    for msg in messages:
        err = msg.error()
        if err is not None:
            if getattr(err, "fatal", lambda: False)():
                raise RuntimeError(f"fatal Kafka error: {err}")
            log.warning("Kafka: %s", err)
            continue
        tp, offset = (msg.topic(), msg.partition()), msg.offset()
        batch.first_offsets.setdefault(tp, offset)
        batch.next_offsets[tp] = max(batch.next_offsets.get(tp, 0), offset + 1)
        value = msg.value()
        try:
            if value is None:
                raise ValueError("empty message")
            record = json.loads(value)
        except (ValueError, UnicodeDecodeError) as e:
            batch.rejected.append((_raw_text(value), f"not valid JSON: {e}", tp[1], offset))
            continue
        errors = validate(record)
        if errors:
            batch.rejected.append((_raw_text(value), "; ".join(errors), tp[1], offset))
            continue
        batch.rows.append(bronze_row(record, tp[1], offset))
    return batch


class BronzeStore:
    """The consumer's writes: bronze.raw_records, bronze.rejected_records, ops.pipeline_runs."""

    def __init__(self, url):
        self.url = url
        self._conn = None

    def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=5)
        return self._conn

    def apply_schema(self):
        apply_schema(self._connect())

    def close(self):
        if self._conn is not None:
            self._conn.close()

    def write_batch(self, batch, started_at):
        """Write one batch in one transaction. Returns (inserted, rejected). Raises psycopg.Error
        when the batch could not be written; then nothing was written."""
        conn = self._connect()
        try:
            with conn.transaction():
                rejected = list(batch.rejected)
                try:
                    with conn.transaction():  # savepoint
                        inserted = insert_raw_records(conn, batch.rows)
                except (psycopg.DataError, psycopg.IntegrityError) as e:
                    log.warning("batch refused by Postgres (%s); inserting row by row", e)
                    inserted = 0
                    for row in batch.rows:
                        try:
                            with conn.transaction():
                                inserted += insert_raw_records(conn, [row])
                        except (psycopg.DataError, psycopg.IntegrityError) as row_error:
                            reason = f"refused by Postgres: {str(row_error).strip()}"
                            raw = _raw_text(json.dumps(row[:9], default=str))
                            rejected.append((raw, reason, *row[9:]))
                if rejected:
                    with conn.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO bronze.rejected_records"
                            " (raw_value, reason, kafka_partition, kafka_offset)"
                            " VALUES (%s, %s, %s, %s)",
                            rejected,
                        )
                duplicates = len(batch.rows) - inserted - (len(rejected) - len(batch.rejected))
                conn.execute(
                    "INSERT INTO ops.pipeline_runs (stage, status, started_at, finished_at,"
                    " rows_loaded, rows_rejected, message)"
                    " VALUES ('ingest', 'success', %s, now(), %s, %s, %s)",
                    (
                        started_at,
                        inserted,
                        len(rejected),
                        f"{batch.size} message(s): {inserted} inserted, {duplicates} already in"
                        f" bronze, {len(rejected)} rejected",
                    ),
                )
            return inserted, len(rejected)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.close()  # reconnect next time
            raise


def _topic_partition(tp, offset):
    from confluent_kafka import TopicPartition

    return TopicPartition(tp[0], tp[1], offset)


def process_batch(consumer, store, messages, started_at, make_tp=_topic_partition):
    """Write one batch, then commit its offsets. On a database failure, rewind instead."""
    batch = parse_messages(messages)
    if not batch.next_offsets:
        return BatchResult("empty")
    try:
        inserted, rejected = store.write_batch(batch, started_at)
    except psycopg.Error as e:
        log.warning(
            "warehouse write failed, %d message(s) stay in Kafka: %s", batch.size, str(e).strip()
        )
        for tp, offset in batch.first_offsets.items():
            try:
                consumer.seek(make_tp(tp, offset))
            except Exception as seek_error:  # partition revoked meanwhile: it is re-read anyway
                log.warning("could not rewind %s: %s", tp, seek_error)
        return BatchResult("retry")
    # The database has committed; only now commit Kafka. If this fails the batch is re-delivered
    # and the idempotent insert ignores it.
    try:
        consumer.commit(
            offsets=[make_tp(tp, off) for tp, off in batch.next_offsets.items()],
            asynchronous=False,
        )
    except Exception as e:
        log.warning("offset commit failed (the batch will be re-delivered, harmlessly): %s", e)
    duplicates = len(batch.rows) - inserted - (rejected - len(batch.rejected))
    return BatchResult("committed", inserted, duplicates, rejected, batch.next_offsets)


def consumer_lag(consumer, batch_offsets):
    """Messages behind the end of each partition this batch touched (None if unknown). Uses the
    high watermark cached from the last fetch, so it costs no broker round trip."""
    lag = 0
    try:
        for (topic, partition), next_offset in batch_offsets.items():
            _low, high = consumer.get_watermark_offsets(
                _topic_partition((topic, partition), 0), cached=True
            )
            if high < 0:  # not known yet
                return None
            lag += max(0, high - next_offset)
    except Exception:
        return None
    return lag


def run(consumer, store, stop, batch_size, flush_seconds):
    backoff = 1.0
    while not stop.is_set():
        started_at = datetime.now(UTC)
        t0 = time.monotonic()
        messages = consumer.consume(num_messages=batch_size, timeout=flush_seconds)
        if not messages:
            continue
        result = process_batch(consumer, store, messages, started_at)
        if result.status == "retry":
            stop.wait(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        backoff = 1.0
        if result.status == "committed":
            seconds = time.monotonic() - t0
            log.info(
                "batch of %d: %d inserted, %d duplicate, %d rejected, lag %s, %.2fs",
                result.loaded + result.duplicates + result.rejected,
                result.loaded,
                result.duplicates,
                result.rejected,
                consumer_lag(consumer, result.offsets),
                seconds,
            )


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL in the environment or .env.")
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.environ.get("KAFKA_TOPIC", "raw.ecom_records")
    batch_size = int(os.environ.get("CONSUMER_BATCH_SIZE", "1000"))
    flush_seconds = float(os.environ.get("CONSUMER_FLUSH_SECONDS", "2"))

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    store = BronzeStore(url)
    backoff = 1.0
    while not stop.is_set():
        try:
            store.apply_schema()
            break
        except psycopg.Error as e:
            log.warning("warehouse unavailable, retrying in %.0fs: %s", backoff, str(e).strip())
            stop.wait(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": GROUP_ID,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])
    log.info(
        "bronze consumer: topic %s on %s -> database %s, batches of %d or %ss",
        topic,
        bootstrap,
        conninfo_to_dict(url).get("dbname"),
        batch_size,
        f"{flush_seconds:g}",
    )
    try:
        run(consumer, store, stop, batch_size, flush_seconds)
    finally:
        consumer.close()
        store.close()
        log.info("bronze consumer stopped")


if __name__ == "__main__":
    main()
