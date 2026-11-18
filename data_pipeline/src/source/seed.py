"""Seed the simulated source system: create `xom_source` and load data/xomdata/*.csv into it once.

Usage:
  python -m src.source.seed [--dir data/xomdata]

Steps:
  1. Create the database named in SOURCE_DATABASE_URL if it does not exist (connecting to the
     server's `postgres` maintenance database to do so).
  2. Apply sql/source_schema.sql (idempotent).
  3. For each table, reference tables first and sales lines last: if it holds no source rows yet,
     COPY its CSV in, in one transaction, and check the count against manifest.csv. If it was
     already seeded, only check the count. Rows the mock generator added (is_sample = true) are
     left alone and not counted.

Re-running is safe: a seeded table is never truncated or loaded twice. The seed never touches the
warehouse (DATABASE_URL); it refuses to run if both URLs name the same database.
"""

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = ROOT / "sql" / "source_schema.sql"
SOURCE_SCHEMA = "e_commerce"  # schema in xom_source, same as upstream

# (upstream table in the CSV file name, table in xom_source), in load order.
TABLES = [
    ("customer", "customer"),
    ("product", "product"),
    ("region", "region"),
    ("ecom_sales", "sales_line"),
]

log = logging.getLogger("seed")


def read_manifest(path):
    """{upstream_table: source_rows} for the e_commerce schema; the last run listed wins.

    Rows that are not data (a repeated header line) are skipped.
    """
    counts = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("schema") == SOURCE_SCHEMA and (row.get("source_rows") or "").isdigit():
                counts[row["table"]] = int(row["source_rows"])
    return counts


def same_database(url_a, url_b):
    """True when two connection URLs point at the same database on the same server."""
    a, b = conninfo_to_dict(url_a), conninfo_to_dict(url_b)
    keys = ("host", "port", "dbname")
    defaults = {"host": "localhost", "port": "5432"}
    return all(str(a.get(k) or defaults.get(k)) == str(b.get(k) or defaults.get(k)) for k in keys)


def ensure_database(url):
    """Create the database named in `url` if it is missing. Returns True when it was created."""
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname:
        raise ValueError("SOURCE_DATABASE_URL must name a database")
    admin_url = make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if exists:
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        return True


def count_source_rows(conn, table):
    query = sql.SQL("SELECT count(*) FROM {} WHERE NOT is_sample").format(
        sql.Identifier(SOURCE_SCHEMA, table)
    )
    return conn.execute(query).fetchone()[0]


def seed_table(conn, table, csv_path, expected):
    """Load one CSV into an empty table, or verify a seeded one. Returns (rows, loaded)."""
    target = sql.Identifier(SOURCE_SCHEMA, table)
    with conn.transaction():
        conn.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(target))
        existing = count_source_rows(conn, table)
        if existing:
            if expected is not None and existing != expected:
                raise RuntimeError(
                    f"already holds {existing} source rows but the manifest says {expected}"
                )
            return existing, False
        with open(csv_path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f))
            f.seek(0)
            copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                target, sql.SQL(", ").join(sql.Identifier(c) for c in header)
            )
            with conn.cursor().copy(copy_stmt) as copy:
                while chunk := f.read(1 << 20):
                    copy.write(chunk)
        loaded = count_source_rows(conn, table)
        if expected is not None and loaded != expected:
            raise RuntimeError(f"loaded {loaded} rows but the manifest says {expected}")
        return loaded, True


def seed(url, directory):
    """Create and seed xom_source. Returns the number of tables that failed."""
    manifest_path = directory / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{manifest_path} is missing; it holds the expected row counts")
    manifest = read_manifest(manifest_path)

    if ensure_database(url):
        log.info("created database %s", conninfo_to_dict(url)["dbname"])

    failed = 0
    with psycopg.connect(url) as conn:
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        conn.commit()
        log.info("applied %s", SCHEMA_SQL.relative_to(ROOT))
        for upstream, table in TABLES:
            csv_path = directory / f"{SOURCE_SCHEMA}.{upstream}.csv"
            t0 = time.time()
            try:
                if not csv_path.exists():
                    raise FileNotFoundError(f"{csv_path} is missing")
                expected = manifest.get(upstream)
                if expected is None:
                    raise RuntimeError(f"manifest.csv has no row count for {upstream}")
                n, loaded = seed_table(conn, table, csv_path, expected)
                what = "loaded" if loaded else "already seeded"
                log.info(
                    "%s.%s: %s, %s rows (%.1fs)",
                    SOURCE_SCHEMA,
                    table,
                    what,
                    f"{n:,}",
                    time.time() - t0,
                )
            except Exception as e:  # report every table, then exit non-zero
                failed += 1
                log.error("%s.%s: FAILED: %s", SOURCE_SCHEMA, table, e)
    return failed


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dir", default="data/xomdata", help="folder holding the exported CSVs")
    args = ap.parse_args()

    url = os.environ.get("SOURCE_DATABASE_URL")
    if not url:
        sys.exit("Set SOURCE_DATABASE_URL in the environment or .env.")
    warehouse = os.environ.get("DATABASE_URL")
    if warehouse and same_database(url, warehouse):
        sys.exit(
            "SOURCE_DATABASE_URL and DATABASE_URL name the same database; the seed only "
            "writes xom_source and never the warehouse."
        )
    if seed(url, Path(args.dir)):
        sys.exit(1)


if __name__ == "__main__":
    main()
