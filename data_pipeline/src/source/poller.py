"""Source poller: send new xom_source rows to the raw data API.

Usage:
  python -m src.source.poller          # loop every POLLER_INTERVAL_SECONDS
  python -m src.source.poller --once   # one cycle (until caught up), then exit (0 = ok)

Each cycle, for each table in envelope order (customer, product, region, then sales_line):
  1. Read the high-water mark from ops.source_offsets (none yet: send everything).
  2. Read up to POLLER_BATCH_SIZE rows with change_seq above it, oldest first.
  3. Wrap each row in the envelope and POST the batch to API_URL/api/v1/records.
  4. Only on 202, move the mark to the batch's last change_seq. Repeat until the table is drained.

A failed POST stops the cycle; the next tick re-sends from the unchanged mark. A crash between a
202 and the mark update also re-sends that batch; bronze's idempotent insert absorbs both. So the
first run sends the whole history, and a restart resumes from the mark, never from scratch.

The poller reads xom_source and writes only ops.source_offsets in the warehouse.

Known limit: change_seq comes from a sequence, so with several *concurrent* writers a row that
commits late with a lower change_seq could fall behind the mark. The only writers are the seed and
the mock generator, which write one transaction at a time.
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.rows import dict_row

from src.envelope import ENTITIES, SOURCE, to_envelope

log = logging.getLogger("source_poller")

SOURCE_SCHEMA = "e_commerce"
POST_TIMEOUT_SECONDS = 60


class SendError(Exception):
    pass


class SourceReader:
    """Reads xom_source, read-only."""

    def __init__(self, url):
        self.url = url
        self._conn = None

    def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self.url, autocommit=True, row_factory=dict_row, connect_timeout=5
            )
            self._conn.read_only = True
        return self._conn

    def read_batch(self, entity, after, limit):
        table = ENTITIES[entity][0]
        query = sql.SQL(
            "SELECT * FROM {} WHERE change_seq > %s ORDER BY change_seq LIMIT %s"
        ).format(sql.Identifier(SOURCE_SCHEMA, table))
        try:
            return self._connect().execute(query, (after, limit)).fetchall()
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.close()
            raise

    def close(self):
        if self._conn is not None:
            self._conn.close()


class OffsetStore:
    """The poller's high-water marks, ops.source_offsets in the warehouse."""

    def __init__(self, url, source=SOURCE):
        self.url = url
        self.source = source
        self._conn = None

    def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=5)
        return self._conn

    def get(self, entity):
        try:
            row = (
                self._connect()
                .execute(
                    "SELECT last_change_seq FROM ops.source_offsets"
                    " WHERE source = %s AND entity = %s",
                    (self.source, entity),
                )
                .fetchone()
            )
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.close()
            raise
        return row[0] if row else 0

    def set(self, entity, change_seq):
        try:
            self._connect().execute(
                "INSERT INTO ops.source_offsets (source, entity, last_change_seq)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (source, entity) DO UPDATE"
                " SET last_change_seq = excluded.last_change_seq, updated_at = now()",
                (self.source, entity, change_seq),
            )
        except (psycopg.OperationalError, psycopg.InterfaceError):
            self.close()
            raise

    def close(self):
        if self._conn is not None:
            self._conn.close()


def http_sender(api_url, timeout=POST_TIMEOUT_SECONDS):
    """A send(envelopes) -> status function that POSTs to the API."""
    endpoint = api_url.rstrip("/") + "/api/v1/records"

    def send(envelopes):
        body = json.dumps(envelopes, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(500).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(500).decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as e:
            raise SendError(f"API unreachable at {endpoint}: {e}") from e

    return send


def poll_once(reader, offsets, send, batch_size, clock=lambda: datetime.now(UTC)):
    """Send every row past the marks, table by table. Returns {entity: rows sent}. Raises
    SendError when the API does not accept a batch (the mark for that batch is not moved)."""
    sent = {}
    for entity in ENTITIES:  # reference tables first, sales lines last
        sent[entity] = 0
        while True:
            mark = offsets.get(entity)
            rows = reader.read_batch(entity, mark, batch_size)
            if not rows:
                break
            collected_at = clock()
            envelopes = [to_envelope(entity, row, collected_at) for row in rows]
            status, body = send(envelopes)
            if status != 202:
                raise SendError(
                    f"{entity}: API answered {status} for {len(rows)} record(s) after change_seq"
                    f" {mark}: {body.strip()}"
                )
            offsets.set(entity, rows[-1]["change_seq"])
            sent[entity] += len(rows)
            if len(rows) < batch_size:
                break
    return sent


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--once", action="store_true", help="run one cycle, then exit")
    args = ap.parse_args()

    source_url = os.environ.get("SOURCE_DATABASE_URL")
    warehouse_url = os.environ.get("DATABASE_URL")
    api_url = os.environ.get("API_URL")
    if not (source_url and warehouse_url and api_url):
        sys.exit("Set SOURCE_DATABASE_URL, DATABASE_URL and API_URL in the environment or .env.")
    interval = float(os.environ.get("POLLER_INTERVAL_SECONDS", "5"))
    batch_size = int(os.environ.get("POLLER_BATCH_SIZE", "1000"))

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    reader, offsets = SourceReader(source_url), OffsetStore(warehouse_url)
    send = http_sender(api_url)
    log.info(
        "source poller: -> %s, every %ss, batches of %d%s",
        api_url,
        f"{interval:g}",
        batch_size,
        " (once)" if args.once else "",
    )
    try:
        while not stop.is_set():
            started = time.monotonic()
            ok = False
            try:
                sent = poll_once(reader, offsets, send, batch_size)
                ok = True
                if any(sent.values()):
                    log.info(
                        "sent %s in %.1fs",
                        ", ".join(f"{n:,} {e}" for e, n in sent.items() if n),
                        time.monotonic() - started,
                    )
            except SendError as e:
                log.warning("send failed, retrying next tick: %s", e)
            except psycopg.Error as e:
                log.warning("database unavailable, retrying next tick: %s", str(e).strip())
            if args.once:
                sys.exit(0 if ok else 1)
            stop.wait(max(0.0, interval - (time.monotonic() - started)))
    finally:
        reader.close()
        offsets.close()
        log.info("source poller stopped")


if __name__ == "__main__":
    main()
