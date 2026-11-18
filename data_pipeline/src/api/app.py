"""Raw data API: Flask app factory, JSON under /api/v1.

  GET  /health            liveness, no dependencies
  POST /api/v1/records    envelope check, then publish to Kafka (202, or 503 if not published)
  GET  /api/v1/sources    known sources
  GET  /api/v1/records    raw records read-only from bronze, paged

The interim /api/v1/tables over the `raw` schema is retired; do not bring it back.
"""

import logging
import os
from datetime import date, datetime
from decimal import Decimal

import psycopg
from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from . import db, health, records

log = logging.getLogger(__name__)


def _to_json(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


class JSONProvider(DefaultJSONProvider):
    sort_keys = False  # keep column order
    default = staticmethod(_to_json)


def create_app(config=None):
    app = Flask(__name__)
    app.json = JSONProvider(app)
    app.config.update(
        DATABASE_URL=os.environ.get("DATABASE_URL", ""),
        APP_VERSION=os.environ.get("APP_VERSION", "dev"),
        KAFKA_BOOTSTRAP_SERVERS=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        KAFKA_TOPIC=os.environ.get("KAFKA_TOPIC", "raw.ecom_records"),
        KAFKA_PUBLISH_TIMEOUT_SECONDS=os.environ.get("KAFKA_PUBLISH_TIMEOUT_SECONDS", "15"),
        MAX_RECORDS_PER_REQUEST=5000,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    app.register_blueprint(health.bp)
    app.register_blueprint(records.bp)

    @app.errorhandler(HTTPException)
    def json_error(e):
        return jsonify(error=e.name, message=e.description), e.code

    @app.errorhandler(psycopg.Error)
    def warehouse_unavailable(e):
        log.error("warehouse error: %s", str(e).strip())
        return jsonify(error="Service Unavailable", message="the warehouse is unavailable"), 503

    return app
