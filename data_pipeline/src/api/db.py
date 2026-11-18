"""One read-only Postgres connection per request, opened lazily and closed on teardown."""

import psycopg
from flask import current_app, g
from psycopg.rows import dict_row


def get_conn():
    if "db_conn" not in g:
        conn = psycopg.connect(current_app.config["DATABASE_URL"], row_factory=dict_row)
        conn.read_only = True  # the API never writes
        g.db_conn = conn
    return g.db_conn


def close_conn(_exc=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_conn)
