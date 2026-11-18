import os
import uuid

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import make_conninfo

from src.api.app import create_app
from src.warehouse import apply_schema

load_dotenv()


@pytest.fixture
def app():
    return create_app({"APP_VERSION": "test"})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def scratch_warehouse():
    """A throwaway database on the DATABASE_URL server with sql/schema.sql applied; dropped after
    the test. Never the dev warehouse itself. Skips when Postgres is not reachable."""
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("DATABASE_URL is not set")
    admin = make_conninfo(base, dbname="postgres", connect_timeout=3)
    try:
        psycopg.connect(admin).close()
    except psycopg.Error as e:
        pytest.skip(f"Postgres not reachable: {e}")
    name = f"xom_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(base, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            apply_schema(conn)
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
            conn.execute(drop.format(sql.Identifier(name)))
