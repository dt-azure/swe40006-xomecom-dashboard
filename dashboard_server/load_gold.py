"""Recreate the xom-ecom gold schema, with its rows, in a Postgres database of your choice.

Usage:
  pip install -r dashboard_serve/requirements.txt
  python dashboard_serve/load_gold.py --url postgresql://user:password@localhost:5432/xom_gold
  python dashboard_serve/load_gold.py --check --url ...   # only compare with the files

The URL can also come from GOLD_DATABASE_URL. The database is created if it does not exist.

What it does, in one transaction (all or nothing):
  1. Drops the schema `gold` in that database if it exists, and only that schema.
  2. Applies schema.sql (every gold table, with its column types and descriptions).
  3. Loads data/<table>.csv into each table and checks the row counts against data/manifest.json.
Re-running gives the same result. Before loading, every CSV is checked against its checksum in
the manifest, so an edited or truncated file is caught.

Safety: it refuses a database that has a `bronze` or `silver` schema, i.e. a real pipeline
warehouse, whose gold is built by dbt and must not be overwritten with a snapshot.

Needs only psycopg 3 (see requirements.txt); it does not use the rest of the repository.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "data" / "manifest.json"
SCHEMA_SQL = HERE / "schema.sql"
PIPELINE_SCHEMAS = ("bronze", "silver")


class LoadError(Exception):
    pass


def read_manifest(path=MANIFEST):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def check_files(manifest, base=HERE):
    for entry in manifest["tables"]:
        path = base / entry["file"]
        if not path.exists():
            raise LoadError(f"{entry['file']} is missing")
        if sha256(path) != entry["sha256"]:
            raise LoadError(f"{entry['file']} does not match its checksum in the manifest")


def ensure_database(url):
    """Create the database named in `url` if it is missing. Returns True when it was created."""
    dbname = conninfo_to_dict(url).get("dbname")
    if not dbname:
        raise LoadError("the URL must name a database")
    with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        return True


def refuse_pipeline_warehouse(conn):
    found = [
        r[0]
        for r in conn.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (list(PIPELINE_SCHEMAS),)
        )
    ]
    if found:
        raise LoadError(
            f"this database has the pipeline schema(s) {', '.join(found)}: it looks like a real "
            "warehouse, whose gold dbt builds. Load the snapshot into a separate database."
        )


def table_counts(conn, manifest):
    counts = {}
    for entry in manifest["tables"]:
        counts[entry["table"]] = conn.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("gold", entry["table"]))
        ).fetchone()[0]
    return counts


def load(url, base=HERE, log=print):
    manifest = read_manifest(base / "data" / "manifest.json")
    check_files(manifest, base)
    if ensure_database(url):
        log(f"created database {conninfo_to_dict(url)['dbname']}")
    # Autocommit, so that conn.transaction() below is the one real transaction (not a savepoint
    # inside an implicit one that would be rolled back on close).
    with psycopg.connect(url, autocommit=True) as conn:
        refuse_pipeline_warehouse(conn)
        with conn.transaction():
            conn.execute("SET LOCAL TimeZone = 'UTC'")
            conn.execute("DROP SCHEMA IF EXISTS gold CASCADE")
            conn.execute((base / "schema.sql").read_text(encoding="utf-8"))
            for entry in manifest["tables"]:
                columns = [c["name"] for c in entry["columns"]]
                copy_sql = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                    sql.Identifier("gold", entry["table"]),
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                )
                with open(base / entry["file"], "rb") as f, conn.cursor().copy(copy_sql) as copy:
                    while chunk := f.read(1 << 20):
                        copy.write(chunk)
            counts = table_counts(conn, manifest)
            expected = {e["table"]: e["rows"] for e in manifest["tables"]}
            if counts != expected:
                raise LoadError(f"row counts differ from the manifest: {counts} vs {expected}")
        conn.execute("ANALYZE")
    for table, n in counts.items():
        log(f"  gold.{table}: {n:,} rows")
    log(
        f"loaded {len(counts)} tables, {sum(counts.values()):,} rows "
        f"(snapshot exported {manifest['exported_at']})"
    )
    return counts


def check(url, base=HERE, log=print):
    manifest = read_manifest(base / "data" / "manifest.json")
    with psycopg.connect(url, autocommit=True) as conn:
        counts = table_counts(conn, manifest)
    expected = {e["table"]: e["rows"] for e in manifest["tables"]}
    for table, n in counts.items():
        mark = "ok" if n == expected[table] else f"MISMATCH (expected {expected[table]:,})"
        log(f"  gold.{table}: {n:,} rows {mark}")
    return counts == expected


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--url", default=os.environ.get("GOLD_DATABASE_URL"), help="target database")
    ap.add_argument("--check", action="store_true", help="only compare the database with the files")
    args = ap.parse_args()
    if not args.url:
        sys.exit("Pass --url or set GOLD_DATABASE_URL.")
    try:
        if args.check:
            sys.exit(0 if check(args.url) else 1)
        load(args.url)
    except (LoadError, psycopg.Error) as e:
        sys.exit(f"error: {str(e).strip()}")


if __name__ == "__main__":
    main()
