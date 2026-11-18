"""Export the gold schema into this folder, for the dashboard owner (pipeline side; run from the
repository root with the project venv).

Usage:
  python dashboard_serve/export_gold.py            # reads DATABASE_URL (the dev warehouse)

Writes:
  dashboard_serve/schema.sql          CREATE TABLE for every gold table, with the exact column
                                      types and the descriptions from dbt/models/gold/_gold.yml
  dashboard_serve/data/<table>.csv    every row, CSV with a header, NULL as an empty field
  dashboard_serve/data/manifest.json  row counts, checksums, columns, and the pipeline state the
                                      snapshot was taken at

All tables are read in one REPEATABLE READ transaction, so the files are one consistent snapshot
even if the transform runner rebuilds gold meanwhile. Read-only: nothing in the warehouse changes.
"""

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
GOLD_YML = ROOT / "dbt" / "models" / "gold" / "_gold.yml"

# Row order in the files (the grain of each table), so re-exports diff cleanly.
ORDER_BY = {
    "dim_customer": ["source", "customer_id"],
    "dim_product": ["source", "product_code"],
    "dim_region": ["source", "region_code"],
    "dim_date": ["date_day"],
    "fct_sales_lines": ["source", "row_id"],
    "mart_discount_impact": ["order_month", "category", "discount_band", "is_sample"],
    "mart_segment_pnl": ["order_quarter", "segment", "is_sample"],
    "mart_market_growth": ["order_year", "market", "region", "is_sample"],
    "mart_customer_retention": ["cohort_month", "months_since_first_order", "is_sample"],
}


# Grain stated in schema.sql, where it differs from the row order (dimensions are keyed on their
# surrogate key, which also covers the unknown member).
GRAIN = {
    "dim_customer": ["customer_key"],
    "dim_product": ["product_key"],
    "dim_region": ["region_key"],
    "fct_sales_lines": ["sales_line_key"],
}


def one_line(text):
    return " ".join(str(text).split()) if text else None


def dbt_docs():
    """{table: (description, {column: description})} from the gold models' YAML."""
    docs = {}
    for model in yaml.safe_load(GOLD_YML.read_text(encoding="utf-8")).get("models", []):
        columns = {c["name"]: one_line(c.get("description")) for c in model.get("columns", [])}
        docs[model["name"]] = (one_line(model.get("description")), columns)
    return docs


def gold_tables(conn):
    """{table: [(column, exact type), ...]} for every table in gold, in column order."""
    rows = conn.execute(
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)"
        " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped"
        " WHERE n.nspname = 'gold' AND c.relkind IN ('r', 'p')"
        " ORDER BY c.relname, a.attnum"
    ).fetchall()
    tables = {}
    for table, column, col_type in rows:
        tables.setdefault(table, []).append((column, col_type))
    return tables


def literal(text):
    return "'" + text.replace("'", "''") + "'"


def schema_sql(tables, docs, exported_at):
    out = [
        "-- The gold schema of the xom-ecom pipeline, as exported on "
        f"{exported_at} by dashboard_serve/export_gold.py.",
        "-- Generated: do not edit by hand. load_gold.py applies it to an empty gold schema.",
        "-- In the real warehouse these tables are built by dbt; constraints are not declared",
        "-- there either, so the grain of each table is given in its comment.",
        "",
        "CREATE SCHEMA IF NOT EXISTS gold;",
        "",
    ]
    for table, columns in tables.items():
        width = max(len(c) for c, _ in columns)
        cols = ",\n".join(f"    {c.ljust(width)}  {t}" for c, t in columns)
        out += [f"CREATE TABLE gold.{table} (", cols, ");", ""]
        description, col_docs = docs.get(table, (None, {}))
        grain = ", ".join(GRAIN.get(table) or ORDER_BY.get(table, []))
        comment = " ".join(x for x in [description, f"Grain: {grain}." if grain else None] if x)
        if comment:
            out.append(f"COMMENT ON TABLE gold.{table} IS {literal(comment)};")
        for column, _type in columns:
            if col_docs.get(column):
                out.append(
                    f"COMMENT ON COLUMN gold.{table}.{column} IS {literal(col_docs[column])};"
                )
        out.append("")
    return "\n".join(out)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def main():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL (the warehouse to export from) in the environment or .env.")
    exported_at = datetime.now(UTC).replace(microsecond=0)
    DATA.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(url) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            conn.execute("SET LOCAL TimeZone = 'UTC'")
            tables = gold_tables(conn)
            if not tables:
                sys.exit("The gold schema has no tables; run the pipeline (dbt build) first.")
            last = conn.execute(
                "SELECT run_id, finished_at, watermark FROM ops.pipeline_runs"
                " WHERE stage = 'transform' AND status = 'success'"
                " ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            latest_status = conn.execute(
                "SELECT status FROM ops.pipeline_runs WHERE stage = 'transform'"
                " ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            date_range = conn.execute(
                "SELECT min(order_date), max(order_date),"
                " count(*) FILTER (WHERE is_sample) FROM gold.fct_sales_lines"
            ).fetchone()

            entries = []
            for table, columns in tables.items():
                names = [c for c, _ in columns]
                order = ORDER_BY.get(table) or names[:1]
                query = sql.SQL(
                    "COPY (SELECT {} FROM {} ORDER BY {}) TO STDOUT WITH (FORMAT csv, HEADER true)"
                ).format(
                    sql.SQL(", ").join(sql.Identifier(c) for c in names),
                    sql.Identifier("gold", table),
                    sql.SQL(", ").join(sql.Identifier(c) for c in order),
                )
                path = DATA / f"{table}.csv"
                with open(path, "wb") as f, conn.cursor().copy(query) as copy:
                    for chunk in copy:
                        f.write(chunk)
                rows = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("gold", table))
                ).fetchone()[0]
                entries.append(
                    {
                        "table": table,
                        "file": f"data/{path.name}",
                        "rows": rows,
                        "sha256": sha256(path),
                        "columns": [{"name": c, "type": t} for c, t in columns],
                    }
                )
                print(f"  gold.{table}: {rows:,} rows -> {path.relative_to(ROOT)}")

    if latest_status and latest_status[0] != "success":
        print(
            f"warning: the latest transform run is '{latest_status[0]}';"
            " gold is from the last successful one"
        )
    (HERE / "schema.sql").write_text(schema_sql(tables, dbt_docs(), exported_at.isoformat()))
    manifest = {
        "exported_at": exported_at.isoformat(),
        "exported_from": conninfo_to_dict(url).get("dbname"),
        "last_successful_transform": {
            "run_id": last[0] if last else None,
            "finished_at": last[1].isoformat() if last else None,
            "bronze_watermark": last[2].isoformat() if last and last[2] else None,
        },
        "fct_sales_lines_order_dates": {
            "first": date_range[0].isoformat() if date_range[0] else None,
            "last": date_range[1].isoformat() if date_range[1] else None,
            "sample_rows": date_range[2],
        },
        "csv": {
            "format": "csv",
            "header": True,
            "null": "empty unquoted field",
            "encoding": "utf-8",
        },
        "tables": entries,
    }
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(entries)} tables, {sum(e['rows'] for e in entries):,} rows")


if __name__ == "__main__":
    main()
