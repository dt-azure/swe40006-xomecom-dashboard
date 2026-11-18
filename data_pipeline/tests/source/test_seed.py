"""Seed loader: manifest parsing, the warehouse guard, and a real load into a throwaway database."""

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from src.source import seed

MANIFEST_HEADER = "schema,table,source_rows,written_rows,exported_at\n"

FIXTURE_CSVS = {
    "customer": (
        "customer_id,first_name,last_name,birth_date,marital_status,gender,email_address,"
        "annual_income,education_level,occupation,home_owner\n"
        "C-1,Ann,Lee,1990-01-02,S,F,ann@example.com,40000,Bachelors,Clerical,Y\n"
        "C-2,Bo,Kim,1985-05-06,M,,bo@example.com,,Graduate Degree,Management,N\n"
    ),
    "product": (
        "product_code,product,category,subcategory\n"
        'P1,Hand Cream,Body care,"bath oils, bubbles and soaks"\n'
    ),
    "region": (
        "region_code,city,state,country,country_latitude,country_longitude,region,market\n"
        "R1,Herat,Hirat,Afghanistan,33.939110,67.709953,Southern Asia,Asia Pacific\n"
    ),
    "ecom_sales": (
        "row_id,order_id,order_date,customer_id,segment,region_code,product_code,quantity,"
        "sales,discount,profit\n"
        "1,MX-2015-SC2057582-42279,2023-10-02,C-1,Consumer,R1,P1,3,48.00,0.00,19.20\n"
        "2,MX-2015-SC2057582-42279,2023-10-02,C-1,Consumer,R9,P1,1,16.00,0.10,-1.50\n"
        "3,MX-2013-KW1657028-41562,2021-10-15,C-2,Corporate,R1,P1,8,48.00,0.00,7.20\n"
    ),
}
FIXTURE_COUNTS = {"customer": 2, "product": 1, "region": 1, "ecom_sales": 3}


def write_fixture(directory, counts=FIXTURE_COUNTS):
    for upstream, body in FIXTURE_CSVS.items():
        (directory / f"e_commerce.{upstream}.csv").write_text(body, encoding="utf-8")
    rows = "".join(f"e_commerce,{t},{n},{n},2026-11-16 09:29:36\n" for t, n in counts.items())
    (directory / "manifest.csv").write_text(MANIFEST_HEADER + rows, encoding="utf-8")


# --- unit tests ------------------------------------------------------------------------------


def test_manifest_last_run_wins_and_stray_headers_are_skipped(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text(
        MANIFEST_HEADER
        + "e_commerce,customer,10,10,2026-11-15 10:00:00\n"
        + MANIFEST_HEADER
        + "e_commerce,customer,12,12,2026-11-16 10:00:00\n"
        + "other,customer,99,99,2026-11-16 10:00:00\n",
        encoding="utf-8",
    )
    assert seed.read_manifest(path) == {"customer": 12}


def test_same_database_compares_host_port_and_name():
    a = "postgresql://xom:xom@localhost:5434/xom"
    assert seed.same_database(a, "postgresql://other:pw@localhost:5434/xom")
    assert not seed.same_database(a, "postgresql://xom:xom@localhost:5434/xom_source")
    assert not seed.same_database(a, "postgresql://xom:xom@localhost:5435/xom")


def test_load_order_puts_sales_lines_last():
    assert [t for _, t in seed.TABLES][-1] == "sales_line"


# --- against a real Postgres -----------------------------------------------------------------


@pytest.fixture
def scratch_db():
    """A throwaway database on the local server, dropped afterwards. Never the real xom_source."""
    base = os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("no SOURCE_DATABASE_URL or DATABASE_URL to reach a Postgres server")
    admin = make_conninfo(base, dbname="postgres", connect_timeout=3)
    try:
        psycopg.connect(admin).close()
    except psycopg.Error as e:
        pytest.skip(f"Postgres not reachable: {e}")
    name = f"xom_source_test_{uuid.uuid4().hex[:8]}"
    yield make_conninfo(base, dbname=name)
    with psycopg.connect(admin, autocommit=True) as conn:
        drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
        conn.execute(drop.format(sql.Identifier(name)))


def table_state(url):
    """{table: (rows, any sample row, change_seq values)}."""
    query = sql.SQL("SELECT count(*), bool_or(is_sample), array_agg(change_seq ORDER BY 1) FROM {}")
    with psycopg.connect(url) as conn:
        return {
            t: conn.execute(query.format(sql.Identifier("e_commerce", t))).fetchone()
            for _, t in seed.TABLES
        }


def test_seed_creates_and_loads_then_reruns_without_reloading(scratch_db, tmp_path):
    write_fixture(tmp_path)
    assert seed.seed(scratch_db, tmp_path) == 0

    first = table_state(scratch_db)
    assert {t: n for t, (n, _, _) in first.items()} == {
        "customer": 2,
        "product": 1,
        "region": 1,
        "sales_line": 3,
    }
    assert not any(sample for _, sample, _ in first.values())
    seqs = [s for _, _, arr in first.values() for s in arr]
    assert len(seqs) == len(set(seqs)), "change_seq comes from one shared sequence"

    assert seed.seed(scratch_db, tmp_path) == 0
    assert table_state(scratch_db) == first, "a re-run must not load or renumber anything"


def test_seed_keeps_source_values_as_stored(scratch_db, tmp_path):
    write_fixture(tmp_path)
    seed.seed(scratch_db, tmp_path)
    with psycopg.connect(scratch_db) as conn:
        gender, income = conn.execute(
            "SELECT gender, annual_income FROM e_commerce.customer WHERE customer_id = 'C-2'"
        ).fetchone()
        orphan = conn.execute(
            "SELECT region_code, profit FROM e_commerce.sales_line WHERE row_id = 2"
        ).fetchone()
    assert gender is None and income is None, "missing stays NULL"
    assert orphan[0] == "R9", "orphan references are kept; there are no foreign keys"
    assert str(orphan[1]) == "-1.50"


def test_update_bumps_change_seq(scratch_db, tmp_path):
    write_fixture(tmp_path)
    seed.seed(scratch_db, tmp_path)
    with psycopg.connect(scratch_db) as conn:
        before = conn.execute(
            "SELECT max(change_seq) FROM ("
            " SELECT change_seq FROM e_commerce.customer UNION ALL"
            " SELECT change_seq FROM e_commerce.sales_line) s"
        ).fetchone()[0]
        after = conn.execute(
            "UPDATE e_commerce.customer SET occupation = 'Professional'"
            " WHERE customer_id = 'C-1' RETURNING change_seq"
        ).fetchone()[0]
    assert after > before


def test_count_mismatch_fails_that_table_only(scratch_db, tmp_path):
    write_fixture(tmp_path, counts={**FIXTURE_COUNTS, "region": 5})
    assert seed.seed(scratch_db, tmp_path) == 1
    state = table_state(scratch_db)
    assert state["region"][0] == 0, "a failed table is rolled back"
    assert state["sales_line"][0] == 3


def test_sample_rows_are_not_counted_against_the_manifest(scratch_db, tmp_path):
    write_fixture(tmp_path)
    seed.seed(scratch_db, tmp_path)
    with psycopg.connect(scratch_db) as conn:
        conn.execute(
            "INSERT INTO e_commerce.sales_line (row_id, order_date, quantity, is_sample)"
            " VALUES (99, current_date, 1, true)"
        )
    assert seed.seed(scratch_db, tmp_path) == 0
