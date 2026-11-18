"""Envelope building and payload hashing, shared by the poller, API and consumer."""

from datetime import UTC, date, datetime
from decimal import Decimal

from src.envelope import ENTITIES, message_key, payload_hash, to_envelope, validate

COLLECTED = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
LINE = {
    "row_id": 1,
    "order_id": "MX-2015-SC2057582-42279",
    "order_date": date(2023, 10, 2),
    "customer_id": "SC-2057582",
    "segment": "Consumer",
    "region_code": "R2140",
    "product_code": "P000409",
    "quantity": 3,
    "sales": Decimal("48.00"),
    "discount": Decimal("0.00"),
    "profit": Decimal("19.20"),
    "is_sample": False,
    "change_seq": 42,
}


def test_sales_line_envelope_fields():
    env = to_envelope("sales_line", LINE, COLLECTED)
    assert env["source"] == "xom_ecom"
    assert env["entity"] == "sales_line"
    assert env["record_id"] == "1"
    assert env["event_at"] == "2023-10-02"
    assert env["collected_at"] == "2026-11-17T09:00:00+00:00"
    assert env["is_sample"] is False


def test_payload_leaves_out_technical_columns_and_keeps_values():
    payload = to_envelope("sales_line", LINE, COLLECTED)["payload"]
    assert "is_sample" not in payload and "change_seq" not in payload
    assert payload["sales"] == 48.0 and payload["profit"] == 19.2
    assert payload["order_date"] == "2023-10-02"


def test_missing_values_stay_null():
    row = {"customer_id": "C-1", "gender": None, "annual_income": None, "is_sample": True}
    env = to_envelope("customer", row, COLLECTED)
    assert env["payload"] == {"customer_id": "C-1", "gender": None, "annual_income": None}
    assert env["event_at"] is None
    assert env["is_sample"] is True


def test_reference_entities_come_before_sales_lines():
    assert list(ENTITIES)[-1] == "sales_line"


def test_payload_hash_ignores_key_order_but_not_values():
    a = {"row_id": 1, "sales": 48.0}
    assert payload_hash(a) == payload_hash({"sales": 48.0, "row_id": 1})
    assert payload_hash(a) != payload_hash({"row_id": 1, "sales": 47.0})
    assert len(payload_hash(a)) == 64


# --- source_version, validation and the Kafka key ---------------------------------------------


def valid_record(**changes):
    env = to_envelope("sales_line", LINE, COLLECTED)
    env.update(changes)
    return env


def test_source_version_is_the_change_seq():
    assert to_envelope("sales_line", LINE, COLLECTED)["source_version"] == 42
    assert to_envelope("customer", {"customer_id": "C-1"}, COLLECTED)["source_version"] is None


def test_a_built_envelope_is_valid():
    assert validate(valid_record()) == []
    assert validate(valid_record(event_at=None, source_version=None)) == []


def test_missing_fields_are_named():
    env = valid_record()
    del env["payload"], env["collected_at"]
    assert validate(env) == ["missing field: collected_at", "missing field: payload"]


def test_bad_envelope_values_are_rejected():
    cases = {
        "unknown source": valid_record(source="other_shop"),
        "entity must be one of": valid_record(entity="invoice"),
        "record_id must be": valid_record(record_id=""),
        "is_sample must be": valid_record(is_sample="false"),
        "payload must be": valid_record(payload=[1, 2]),
        "source_version must be": valid_record(source_version="7"),
        "collected_at must be": valid_record(collected_at=None),
        "event_at must be": valid_record(event_at="yesterday"),
    }
    for expected, record in cases.items():
        errors = validate(record)
        assert any(expected in e for e in errors), (expected, errors)
    assert validate("not an object") == ["record must be a JSON object"]
    assert validate(valid_record(source_version=True)), "a boolean is not a version"
    assert validate(valid_record(source_version=2**63)), "beyond bigint"


def test_values_postgres_cannot_store_are_rejected():
    nan = valid_record(payload={**valid_record()["payload"], "sales": float("nan")})
    nul = valid_record(payload={**valid_record()["payload"], "order_id": "A\x00B"})
    assert any("NaN" in e for e in validate(nan))
    assert any("NUL" in e for e in validate(nul))


def test_message_key_keeps_versions_of_one_record_together():
    assert message_key(valid_record()) == "xom_ecom:sales_line:1"
