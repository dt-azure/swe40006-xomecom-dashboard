"""The record envelope: how one source row travels from xom_source through the API and Kafka to
bronze. Shared by the poller (builds envelopes), the API and the consumer (both check them with
`validate`), and the consumer and CI loader (hash payloads for idempotent inserts).

`source_version` is the source's own version of the row (xom_source `change_seq`), or null when a
source has none. It is part of bronze's uniqueness key, so a record that changes A -> B -> A keeps
its last version instead of colliding with the first one.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

SOURCE = "xom_ecom"
KNOWN_SOURCES = (SOURCE,)

# entity -> (xom_source table, key column, business-time column or None), in send order:
# reference tables before sales lines.
ENTITIES = {
    "customer": ("customer", "customer_id", None),
    "product": ("product", "product_code", None),
    "region": ("region", "region_code", None),
    "sales_line": ("sales_line", "row_id", "order_date"),
}

# Columns of xom_source that are bookkeeping, not part of the record.
TECHNICAL_COLUMNS = frozenset({"is_sample", "change_seq"})


def _json_value(value):
    if isinstance(value, Decimal):
        # numeric(10,2) / numeric(10,6) values fit a float exactly enough to round-trip; silver
        # casts them back to numeric.
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def to_envelope(entity, row, collected_at):
    """Wrap one xom_source row (a dict of column -> value) in the envelope."""
    _table, key_column, event_column = ENTITIES[entity]
    payload = {k: _json_value(v) for k, v in row.items() if k not in TECHNICAL_COLUMNS}
    event_at = row.get(event_column) if event_column else None
    return {
        "source": SOURCE,
        "entity": entity,
        "record_id": str(row[key_column]),
        "event_at": _json_value(event_at) if event_at is not None else None,
        "collected_at": _json_value(collected_at),
        "is_sample": bool(row.get("is_sample", False)),
        "source_version": row.get("change_seq"),
        "payload": payload,
    }


def payload_hash(payload):
    """sha256 of the payload as canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


REQUIRED_FIELDS = (
    "source",
    "entity",
    "record_id",
    "event_at",
    "collected_at",
    "is_sample",
    "payload",
)


def parse_time(value):
    """An ISO-8601 date or timestamp string as a datetime; naive values are taken as UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def validate(record):
    """Check the envelope only (never the payload's contents). Returns a list of problems; an
    empty list means the record is valid. Timestamps must parse, so that a record that passes
    here can always be inserted into bronze."""
    if not isinstance(record, dict):
        return ["record must be a JSON object"]
    errors = [f"missing field: {name}" for name in REQUIRED_FIELDS if name not in record]
    if errors:
        return errors
    if record["source"] not in KNOWN_SOURCES:
        errors.append(f"unknown source: {record['source']!r}")
    if record["entity"] not in ENTITIES:
        errors.append(f"entity must be one of {sorted(ENTITIES)}, not {record['entity']!r}")
    if not isinstance(record["record_id"], str) or not record["record_id"].strip():
        errors.append("record_id must be a non-empty string")
    if not isinstance(record["is_sample"], bool):
        errors.append("is_sample must be true or false")
    if not isinstance(record["payload"], dict):
        errors.append("payload must be a JSON object")
    version = record.get("source_version")
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int) or not -(2**63) <= version < 2**63
    ):
        errors.append("source_version must be a 64-bit integer or null")
    # Values Postgres cannot store (jsonb rejects NaN and \u0000; text rejects NUL) would fail the
    # bronze insert, so they are caught here instead.
    try:
        text = json.dumps(record, allow_nan=False)
    except ValueError:
        errors.append("record contains NaN or Infinity, which JSON cannot hold")
    else:
        if "\\u0000" in text:
            errors.append("record contains a NUL character, which Postgres cannot store")
    for name, nullable in (("event_at", True), ("collected_at", False)):
        value = record[name]
        if value is None and nullable:
            continue
        try:
            if not isinstance(value, str):
                raise TypeError
            parse_time(value)
        except (TypeError, ValueError):
            what = "an ISO-8601 timestamp" + (" or null" if nullable else "")
            errors.append(f"{name} must be {what}")
    return errors


def message_key(record):
    """Kafka message key: versions of one record share it, so they stay in order."""
    return f"{record['source']}:{record['entity']}:{record['record_id']}"
