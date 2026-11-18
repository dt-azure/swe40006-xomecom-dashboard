"""Extract: dump schemas of the source SQL Server to local CSV files.

Produces, under --out:
  schema.mssql.sql          T-SQL to recreate the selected schemas (reference only; the local
                            Postgres DDL lives in sql/schema.sql)
  <schema>.<table>.csv      one CSV per table (header row, UTF-8, RFC 4180 quoting)
  manifest.csv              source row count vs rows written, per table and run

CSV conventions: NULL -> empty field; bit -> 0/1; dates/times ISO at full source precision;
decimals in plain notation; binary as 0x-prefixed hex.

Usage:
  python -m src.extract.export_sqlserver --schema e_commerce \
      [--out data/xomdata] [--workers 4] [--force]

Connection comes from MSSQL_SERVER, MSSQL_DATABASE, MSSQL_USER, MSSQL_PASSWORD (see .env.example).
Re-running skips tables whose CSV already finished (use --force to redo them).
"""

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyodbc
from dotenv import load_dotenv


def connect():
    load_dotenv()
    server = os.environ.get("MSSQL_SERVER", "db.xomdata.com,1433")
    database = os.environ.get("MSSQL_DATABASE", "xomdata_dataset")
    user = os.environ.get("MSSQL_USER")
    password = os.environ.get("MSSQL_PASSWORD")
    if not user or not password:
        sys.exit("Set MSSQL_USER and MSSQL_PASSWORD in the environment or .env.")
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};DATABASE={database};UID={user};PWD={password};"
        "Encrypt=yes;TrustServerCertificate=yes;",
        timeout=30,
    )


def q(name):
    return "[" + name.replace("]", "]]") + "]"


def lit(s):
    return "N'" + s.replace("'", "''") + "'"


# --------------------------------------------------------------------------- schema

SCRIPTED_OBJECT_TYPES = {"U", "PK", "UQ", "F", "D", "C"}  # table, pk, unique, fk, default, check


def type_sql(t, max_len, prec, scale):
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if max_len == -1 else max_len // 2})"
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if max_len == -1 else max_len})"
    if t in ("decimal", "numeric"):
        return f"{t}({prec},{scale})"
    if t in ("datetime2", "time", "datetimeoffset"):
        return f"{t}({scale})"
    if t == "float":
        return f"float({prec})"
    return t


def script_schema(conn, schemas=None):
    """Return (T-SQL DDL, [(object_id, schema, table)]) for the given schemas (None = all)."""
    c = conn.cursor()
    db_name = c.execute("SELECT DB_NAME()").fetchone()[0]
    db_collation = c.execute("SELECT DATABASEPROPERTYEX(DB_NAME(), 'Collation')").fetchone()[0]
    in_scope = (lambda s: s in schemas) if schemas else (lambda _s: True)

    unsupported = [
        r
        for r in c.execute(
            "SELECT SCHEMA_NAME(schema_id), type_desc, name FROM sys.objects "
            "WHERE is_ms_shipped = 0 AND type NOT IN ({})".format(
                ",".join(f"'{t}'" for t in SCRIPTED_OBJECT_TYPES)
            )
        )
        if in_scope(r[0])
    ]
    if unsupported:
        raise SystemExit(f"Objects this script does not handle: {unsupported}")
    if any(
        in_scope(r[0])
        for r in c.execute("SELECT OBJECT_SCHEMA_NAME(object_id) FROM sys.computed_columns")
    ):
        raise SystemExit("Computed columns are not supported by this script.")
    if c.execute("SELECT COUNT(*) FROM sys.types WHERE is_user_defined = 1").fetchone()[0]:
        raise SystemExit("User-defined types are not supported by this script.")

    tables = [
        r
        for r in c.execute(
            "SELECT t.object_id, s.name, t.name FROM sys.tables t "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id WHERE t.is_ms_shipped = 0 "
            "ORDER BY s.name, t.name"
        )
        if in_scope(r[1])
    ]
    if schemas:
        missing = set(schemas) - {s for _, s, _ in tables}
        if missing:
            raise SystemExit(f"No tables found in schema(s): {sorted(missing)}")
    tname = {oid: f"{q(s)}.{q(n)}" for oid, s, n in tables}

    cols = {}
    for r in c.execute(
        """SELECT c.object_id, c.name, TYPE_NAME(c.user_type_id), c.max_length,
                  c.precision, c.scale, c.is_nullable, c.collation_name, c.is_identity,
                  CAST(ic.seed_value AS bigint), CAST(ic.increment_value AS bigint),
                  dc.name, dc.definition
           FROM sys.columns c
           JOIN sys.tables t ON t.object_id = c.object_id
           LEFT JOIN sys.identity_columns ic
                  ON ic.object_id = c.object_id AND ic.column_id = c.column_id
           LEFT JOIN sys.default_constraints dc
                  ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
           ORDER BY c.object_id, c.column_id"""
    ):
        (oid, name, typ, max_len, prec, scale, nullable, coll, is_ident, seed, inc, dname, ddef) = r
        if oid not in tname:
            continue
        line = f"    {q(name)} {type_sql(typ, max_len, prec, scale)}"
        if coll and coll != db_collation:
            line += f" COLLATE {coll}"
        if is_ident:
            line += f" IDENTITY({seed},{inc})"
        if ddef:
            line += f" CONSTRAINT {q(dname)} DEFAULT {ddef}"
        line += " NULL" if nullable else " NOT NULL"
        cols.setdefault(oid, []).append(line)

    # indexes incl. PK / unique constraints
    idx_cols = {}
    for oid, iid, cname, desc, included in c.execute(
        """SELECT ic.object_id, ic.index_id, c.name, ic.is_descending_key, ic.is_included_column
           FROM sys.index_columns ic
           JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
           JOIN sys.tables t ON t.object_id = ic.object_id
           ORDER BY ic.object_id, ic.index_id, ic.key_ordinal, ic.index_column_id"""
    ):
        key, inc = idx_cols.setdefault((oid, iid), ([], []))
        (inc if included else key).append(q(cname) + (" DESC" if desc else ""))

    index_sql = []
    for oid, iid, name, typ, is_pk, is_uq_con, is_unique, has_filter, filt in c.execute(
        """SELECT i.object_id, i.index_id, i.name, i.type_desc, i.is_primary_key,
                  i.is_unique_constraint, i.is_unique, i.has_filter, i.filter_definition
           FROM sys.indexes i JOIN sys.tables t ON t.object_id = i.object_id
           WHERE i.type > 0 AND i.is_hypothetical = 0
           ORDER BY i.object_id, i.index_id"""
    ):
        if oid not in tname:
            continue
        if typ not in ("CLUSTERED", "NONCLUSTERED"):
            raise SystemExit(f"Unsupported index type {typ} on {tname[oid]} ({name})")
        key, inc = idx_cols[(oid, iid)]
        if is_pk or is_uq_con:
            kind = "PRIMARY KEY" if is_pk else "UNIQUE"
            index_sql.append(
                f"ALTER TABLE {tname[oid]} ADD CONSTRAINT {q(name)} {kind} {typ} "
                f"({', '.join(key)});"
            )
        else:
            s = (
                f"CREATE {'UNIQUE ' if is_unique else ''}{typ} INDEX {q(name)} "
                f"ON {tname[oid]} ({', '.join(key)})"
            )
            if inc:
                s += f" INCLUDE ({', '.join(inc)})"
            if has_filter:
                s += f" WHERE {filt}"
            index_sql.append(s + ";")

    check_sql = [
        f"ALTER TABLE {tname[oid]} WITH {'NOCHECK' if untrusted else 'CHECK'} "
        f"ADD CONSTRAINT {q(name)} CHECK {definition};"
        + (f"\nALTER TABLE {tname[oid]} NOCHECK CONSTRAINT {q(name)};" if disabled else "")
        for oid, name, definition, untrusted, disabled in c.execute(
            "SELECT parent_object_id, name, definition, is_not_trusted, is_disabled "
            "FROM sys.check_constraints"
        )
        if oid in tname
    ]

    fk_cols = {}
    for fid, pc, rc in c.execute(
        """SELECT fkc.constraint_object_id, pc.name, rc.name FROM sys.foreign_key_columns fkc
           JOIN sys.columns pc
             ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
           JOIN sys.columns rc
             ON rc.object_id = fkc.referenced_object_id
            AND rc.column_id = fkc.referenced_column_id
           ORDER BY fkc.constraint_object_id, fkc.constraint_column_id"""
    ):
        a, b = fk_cols.setdefault(fid, ([], []))
        a.append(q(pc))
        b.append(q(rc))

    fk_sql = []
    for fid, name, pid, rid, on_del, on_upd, untrusted, disabled in c.execute(
        """SELECT object_id, name, parent_object_id, referenced_object_id,
                  delete_referential_action_desc, update_referential_action_desc,
                  is_not_trusted, is_disabled
           FROM sys.foreign_keys ORDER BY name"""
    ):
        if pid not in tname:
            continue
        if rid not in tname:
            raise SystemExit(
                f"FK {name} on {tname[pid]} references a table outside the selected schemas"
            )
        a, b = fk_cols[fid]
        s = (
            f"ALTER TABLE {tname[pid]} WITH {'NOCHECK' if untrusted else 'CHECK'} "
            f"ADD CONSTRAINT {q(name)} FOREIGN KEY ({', '.join(a)}) "
            f"REFERENCES {tname[rid]} ({', '.join(b)})"
        )
        if on_del != "NO_ACTION":
            s += f" ON DELETE {on_del.replace('_', ' ')}"
        if on_upd != "NO_ACTION":
            s += f" ON UPDATE {on_upd.replace('_', ' ')}"
        s += ";"
        if disabled:
            s += f"\nALTER TABLE {tname[pid]} NOCHECK CONSTRAINT {q(name)};"
        fk_sql.append(s)

    schema_names = sorted({s for _, s, _ in tables})
    out = [
        f"-- Schema of [{db_name}] scripted {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"-- Source collation: {db_collation}. Run inside the target database.",
        "-- Load the CSVs after the tables exist; the foreign keys are at the end of this file.",
        "SET NOCOUNT ON;",
        "GO",
        "",
        "-- Schemas",
    ]
    out += [
        f"IF SCHEMA_ID({lit(s)}) IS NULL EXEC({lit('CREATE SCHEMA ' + q(s))});"
        for s in schema_names
    ]
    out += ["GO", "", "-- Tables"]
    for oid, _, _ in tables:
        out += [f"CREATE TABLE {tname[oid]} (", ",\n".join(cols[oid]), ");", "GO"]
    out += ["", "-- Primary keys, unique constraints, indexes"] + index_sql + ["GO"]
    if check_sql:
        out += ["", "-- Check constraints"] + check_sql + ["GO"]
    out += ["", "-- Foreign keys"] + fk_sql + ["GO", ""]
    return "\n".join(out), tables


# --------------------------------------------------------------------------- data

SELECT_EXPR = {
    "bit": "CAST({c} AS tinyint)",
    "decimal": "CONVERT(varchar(50), {c})",
    "numeric": "CONVERT(varchar(50), {c})",
    "money": "CONVERT(varchar(50), {c}, 2)",
    "smallmoney": "CONVERT(varchar(50), {c}, 2)",
    "float": "CONVERT(varchar(30), {c}, 3)",
    "real": "CONVERT(varchar(30), {c}, 3)",
    "datetime": "CONVERT(varchar(30), {c}, 121)",
    "datetime2": "CONVERT(varchar(30), {c}, 121)",
    "smalldatetime": "CONVERT(varchar(30), {c}, 121)",
    "time": "CONVERT(varchar(30), {c}, 121)",
    "datetimeoffset": "CONVERT(varchar(40), {c}, 121)",
    "date": "CONVERT(varchar(10), {c}, 23)",
    "ntext": "CAST({c} AS nvarchar(max))",
    "text": "CAST({c} AS varchar(max))",
    "xml": "CAST({c} AS nvarchar(max))",
    "uniqueidentifier": "CAST({c} AS char(36))",
    "binary": "CONVERT(varchar(max), {c}, 1)",
    "varbinary": "CONVERT(varchar(max), {c}, 1)",
}
PASSTHROUGH = {"int", "bigint", "smallint", "tinyint", "nvarchar", "nchar", "varchar", "char"}


def export_table(schema, table, out_dir, force):
    final = out_dir / f"{schema}.{table}.csv"
    if final.exists() and not force:
        return schema, table, None, None, "skipped (exists)"
    part = final.with_suffix(".csv.part")
    t0 = time.time()
    conn = connect()
    try:
        c = conn.cursor()
        meta = c.execute(
            "SELECT c.name, TYPE_NAME(c.user_type_id) FROM sys.columns c "
            "WHERE c.object_id = OBJECT_ID(?) ORDER BY c.column_id",
            f"{q(schema)}.{q(table)}",
        ).fetchall()
        exprs = []
        for name, typ in meta:
            if typ in SELECT_EXPR:
                exprs.append(SELECT_EXPR[typ].format(c=q(name)))
            elif typ in PASSTHROUGH:
                exprs.append(q(name))
            else:
                raise RuntimeError(f"{schema}.{table}.{name}: unsupported type {typ}")
        expected = c.execute(f"SELECT COUNT_BIG(*) FROM {q(schema)}.{q(table)}").fetchone()[0]
        c.execute(f"SELECT {', '.join(exprs)} FROM {q(schema)}.{q(table)}")
        written = 0
        next_report = 1_000_000
        with open(part, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([n for n, _ in meta])
            while rows := c.fetchmany(20_000):
                w.writerows(rows)
                written += len(rows)
                if written >= next_report:
                    print(f"    {schema}.{table}: {written:,}/{expected:,} rows", flush=True)
                    next_report += 1_000_000
        if written != expected:
            raise RuntimeError(f"{schema}.{table}: wrote {written} rows, expected {expected}")
        part.rename(final)
        return schema, table, expected, written, f"ok in {time.time() - t0:.0f}s"
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default="data/xomdata")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="re-export tables that already have a CSV")
    ap.add_argument("--schema", action="append", help="only this schema (repeatable); default: all")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    conn = connect()
    ddl, tables = script_schema(conn, args.schema)
    (out / "schema.mssql.sql").write_text(ddl, encoding="utf-8")
    print(f"Wrote {out / 'schema.mssql.sql'} ({len(tables)} tables)")

    # biggest tables first so the long ones start early
    sizes = {
        (s, t): n
        for s, t, n in conn.cursor().execute(
            "SELECT s.name, t.name, SUM(p.rows) FROM sys.tables t "
            "JOIN sys.schemas s ON s.schema_id = t.schema_id "
            "JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1) "
            "GROUP BY s.name, t.name"
        )
    }
    conn.close()
    order = sorted(((s, t) for _, s, t in tables), key=lambda st: -sizes.get(st, 0))

    results, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(export_table, s, t, out, args.force): (s, t) for s, t in order}
        for fut in as_completed(futs):
            s, t = futs[fut]
            try:
                r = fut.result()
                results.append(r)
                print(f"[{len(results) + len(failures)}/{len(order)}] {s}.{t}: {r[4]}", flush=True)
            except Exception as e:  # keep going; report at the end
                failures.append((s, t, str(e)))
                done = len(results) + len(failures)
                print(f"[{done}/{len(order)}] {s}.{t}: FAILED {e}", flush=True)

    manifest = out / "manifest.csv"
    mode = "a" if not args.force and manifest.exists() else "w"
    with open(manifest, mode, newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["schema", "table", "source_rows", "written_rows", "exported_at"])
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        for s, t, exp, wr, _status in sorted(results):
            if exp is not None:
                w.writerow([s, t, exp, wr, stamp])

    if failures:
        print(f"\n{len(failures)} table(s) failed; re-run to retry them:")
        for s, t, e in failures:
            print(f"  {s}.{t}: {e}")
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
