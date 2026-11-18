"""dashboard_serve/load_gold.py: the shipped bundle loads into an empty database with the counts in
its manifest, re-running gives the same result, NULL and empty strings survive the CSV round
trip, an edited file is caught, and a real pipeline warehouse is refused."""

import hashlib
import importlib.util
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

BUNDLE = Path(__file__).resolve().parents[2] / "dashboard_serve"
spec = importlib.util.spec_from_file_location("load_gold", BUNDLE / "load_gold.py")
load_gold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load_gold)


@pytest.fixture
def empty_db():
    """A database that does not exist yet (the loader creates it); dropped afterwards."""
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("DATABASE_URL is not set")
    admin = make_conninfo(base, dbname="postgres", connect_timeout=3)
    try:
        psycopg.connect(admin).close()
    except psycopg.Error as e:
        pytest.skip(f"Postgres not reachable: {e}")
    name = f"xom_gold_test_{uuid.uuid4().hex[:8]}"
    yield make_conninfo(base, dbname=name)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def mini_bundle(tmp_path, csv_text):
    (tmp_path / "data").mkdir()
    csv_path = tmp_path / "data" / "dim_x.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    (tmp_path / "schema.sql").write_text(
        "CREATE SCHEMA IF NOT EXISTS gold;\n"
        "CREATE TABLE gold.dim_x (k text, label text, n integer);\n"
    )
    manifest = {
        "exported_at": "2026-11-17T00:00:00+00:00",
        "tables": [
            {
                "table": "dim_x",
                "file": "data/dim_x.csv",
                "rows": csv_text.count("\n") - 1,
                "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "columns": [{"name": c, "type": "text"} for c in ("k", "label", "n")],
            }
        ],
    }
    (tmp_path / "data" / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_the_shipped_bundle_loads_with_the_manifest_counts(empty_db):
    manifest = load_gold.read_manifest()
    expected = {e["table"]: e["rows"] for e in manifest["tables"]}
    assert expected["fct_sales_lines"] > 0
    assert load_gold.load(empty_db, log=lambda *_: None) == expected
    assert load_gold.load(empty_db, log=lambda *_: None) == expected, "re-run gives the same"
    assert load_gold.check(empty_db, log=lambda *_: None)


def test_null_and_empty_string_survive_the_round_trip(empty_db, tmp_path):
    bundle = mini_bundle(tmp_path, 'k,label,n\na,,\nb,"",2\n')
    load_gold.load(empty_db, base=bundle, log=lambda *_: None)
    with psycopg.connect(empty_db) as conn:
        rows = conn.execute("SELECT k, label, n FROM gold.dim_x ORDER BY k").fetchall()
    assert rows == [("a", None, None), ("b", "", 2)]


def test_an_edited_file_is_caught(tmp_path):
    bundle = mini_bundle(tmp_path, "k,label,n\na,x,1\n")
    (bundle / "data" / "dim_x.csv").write_text("k,label,n\na,x,999\n")
    with pytest.raises(load_gold.LoadError, match="checksum"):
        load_gold.check_files(load_gold.read_manifest(bundle / "data" / "manifest.json"), bundle)


def test_a_pipeline_warehouse_is_refused(scratch_warehouse):
    with pytest.raises(load_gold.LoadError, match="pipeline schema"):
        load_gold.load(scratch_warehouse, log=lambda *_: None)
    with psycopg.connect(scratch_warehouse) as conn:
        gold = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'gold'").fetchone()
    assert gold is None, "nothing was touched"
