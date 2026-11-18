"""Record endpoints under /api/v1.

  POST /api/v1/records   one envelope or a list; checks the envelope only, publishes every record
                         to Kafka and answers 202 {"accepted": n}. All or nothing: one invalid
                         record rejects the request (400) and nothing is published. 503 when Kafka
                         does not acknowledge every record.
  GET  /api/v1/sources   the known sources and their entities.
  GET  /api/v1/records   raw records read-only from bronze, paged (page_size default 100, max 500).

The API never writes the warehouse; the only path into bronze is Kafka and the consumer.
"""

import logging

from flask import Blueprint, abort, current_app, jsonify, request

from src.envelope import ENTITIES, KNOWN_SOURCES, message_key, validate

from .db import get_conn
from .publisher import PublishError, get_publisher

log = logging.getLogger(__name__)

bp = Blueprint("records", __name__, url_prefix="/api/v1")

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

RECORD_COLUMNS = (
    "id, source, entity, record_id, event_at, collected_at, is_sample, source_version, payload,"
    " payload_hash, ingested_at, kafka_partition, kafka_offset"
)


@bp.post("/records")
def post_records():
    body = request.get_json(silent=True)
    if body is None:
        abort(400, description="body must be JSON: one record or a list of records")
    records = body if isinstance(body, list) else [body]
    if not records:
        abort(400, description="no records")
    limit = current_app.config["MAX_RECORDS_PER_REQUEST"]
    if len(records) > limit:
        abort(413, description=f"at most {limit} records per request, got {len(records)}")

    problems = []
    for i, record in enumerate(records):
        errors = validate(record)
        if errors:
            problems.append({"index": i, "errors": errors})
    if problems:
        return (
            jsonify(
                error="Bad Request",
                message=f"{len(problems)} of {len(records)} record(s) failed envelope validation;"
                " nothing was published",
                records=problems[:50],
            ),
            400,
        )

    try:
        get_publisher().publish((message_key(r), r) for r in records)
    except PublishError as e:
        log.error("publish of %d record(s) failed: %s", len(records), e)
        return jsonify(error="Service Unavailable", message=str(e)), 503
    return jsonify(accepted=len(records)), 202


@bp.get("/sources")
def list_sources():
    return jsonify(sources=[{"source": s, "entities": list(ENTITIES)} for s in KNOWN_SOURCES])


def _int_arg(name, default, minimum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        abort(400, description=f"{name} must be an integer")
    if value < minimum:
        abort(400, description=f"{name} must be at least {minimum}")
    return value


@bp.get("/records")
def get_records():
    source = request.args.get("source")
    entity = request.args.get("entity")
    if source is not None and source not in KNOWN_SOURCES:
        abort(404, description=f"unknown source: {source!r}")
    if entity is not None and entity not in ENTITIES:
        abort(400, description=f"entity must be one of {sorted(ENTITIES)}")
    page = _int_arg("page", 1, 1)
    page_size = min(_int_arg("page_size", DEFAULT_PAGE_SIZE, 1), MAX_PAGE_SIZE)

    where, params = [], []
    if source is not None:
        where.append("source = %s")
        params.append(source)
    if entity is not None:
        where.append("entity = %s")
        params.append(entity)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    conn = get_conn()
    total = conn.execute(
        f"SELECT count(*) AS n FROM bronze.raw_records{where_sql}", params
    ).fetchone()["n"]
    rows = conn.execute(
        f"SELECT {RECORD_COLUMNS} FROM bronze.raw_records{where_sql}"
        " ORDER BY id LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return jsonify(
        page=page,
        page_size=page_size,
        total=total,
        next_page=page + 1 if page * page_size < total else None,
        records=rows,
    )
