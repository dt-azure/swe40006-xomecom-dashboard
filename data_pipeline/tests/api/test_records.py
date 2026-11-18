"""Record endpoints: accepted posts, bad envelopes, publish failure (503), sources, and paging over
bronze. Kafka is a fake producer; the GET tests read a throwaway database."""

import json
from datetime import UTC, date, datetime

import psycopg
import pytest

from src.api.app import create_app
from src.api.publisher import EXTENSION, KafkaPublisher
from src.envelope import to_envelope
from src.warehouse import bronze_row, insert_raw_records

COLLECTED = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


class FakeError:
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class FakeProducer:
    """Collects produced messages; flush() acknowledges them, fails them, or leaves them queued."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.pending = []
        self.delivered = []
        self.config = None

    def produce(self, topic, key, value, on_delivery):
        if self.mode == "raise":
            from confluent_kafka import KafkaException

            raise KafkaException("broker down")
        self.pending.append((topic, key, value, on_delivery))

    def poll(self, _timeout):
        return 0

    def flush(self, _timeout):
        if self.mode == "timeout":
            return len(self.pending)
        for topic, key, value, cb in self.pending:
            err = FakeError("Broker: Not enough in-sync replicas") if self.mode == "fail" else None
            cb(err, None)
            if self.mode == "ok":
                self.delivered.append((topic, key.decode(), json.loads(value)))
        self.pending = []
        return 0


def make_client(producer, **config):
    app = create_app({"APP_VERSION": "test", **config})

    def factory(cfg):
        producer.config = cfg
        return producer

    app.extensions[EXTENSION] = KafkaPublisher("unused:9092", "raw.ecom_records", 1.0, factory)
    return app.test_client()


def line(row_id=1, **changes):
    row = {
        "row_id": row_id,
        "order_id": "MX-2015-SC2057582-42279",
        "order_date": date(2023, 10, 2),
        "customer_id": "SC-2057582",
        "quantity": 3,
        "sales": 48.0,
        "discount": 0.0,
        "profit": 19.2,
        "is_sample": False,
        "change_seq": 100 + row_id,
    }
    row.update(changes)
    return to_envelope("sales_line", row, COLLECTED)


# --- POST /api/v1/records ---------------------------------------------------------------------


def test_one_record_is_published_and_accepted():
    producer = FakeProducer()
    r = make_client(producer).post("/api/v1/records", json=line())
    assert r.status_code == 202 and r.get_json() == {"accepted": 1}
    [(topic, key, value)] = producer.delivered
    assert topic == "raw.ecom_records"
    assert key == "xom_ecom:sales_line:1"
    assert value == json.loads(json.dumps(line())), "the envelope is published unchanged"


def test_a_list_is_published_in_order():
    producer = FakeProducer()
    r = make_client(producer).post("/api/v1/records", json=[line(1), line(2), line(3)])
    assert r.status_code == 202 and r.get_json() == {"accepted": 3}
    assert [key for _t, key, _v in producer.delivered] == [
        "xom_ecom:sales_line:1",
        "xom_ecom:sales_line:2",
        "xom_ecom:sales_line:3",
    ]


def test_producer_is_configured_for_durable_delivery():
    producer = FakeProducer()
    make_client(producer).post("/api/v1/records", json=line())
    assert producer.config["acks"] == "all"
    assert producer.config["enable.idempotence"] is True


def test_one_bad_record_rejects_the_request_and_nothing_is_published():
    producer = FakeProducer()
    bad = line(2)
    del bad["payload"]
    r = make_client(producer).post(
        "/api/v1/records", json=[line(1), bad, line(3) | {"is_sample": "x"}]
    )
    assert r.status_code == 400
    body = r.get_json()
    assert [p["index"] for p in body["records"]] == [1, 2]
    assert "missing field: payload" in body["records"][0]["errors"]
    assert producer.delivered == [] and producer.pending == []


@pytest.mark.parametrize(
    "body, status",
    [
        ("not json", 400),
        ("[]", 400),
        ('"just a string"', 400),
        (json.dumps(line() | {"entity": "invoice"}), 400),
        (json.dumps(line() | {"source": "elsewhere"}), 400),
    ],
)
def test_bad_bodies(body, status):
    r = make_client(FakeProducer()).post(
        "/api/v1/records", data=body, content_type="application/json"
    )
    assert r.status_code == status
    assert r.get_json()["error"] == "Bad Request"


def test_too_many_records_is_413():
    client = make_client(FakeProducer(), MAX_RECORDS_PER_REQUEST=2)
    r = client.post("/api/v1/records", json=[line(1), line(2), line(3)])
    assert r.status_code == 413


@pytest.mark.parametrize("mode", ["fail", "timeout", "raise"])
def test_publish_failure_is_503_never_success(mode):
    r = make_client(FakeProducer(mode)).post("/api/v1/records", json=[line(1), line(2)])
    assert r.status_code == 503
    assert r.get_json()["error"] == "Service Unavailable"


def test_health_does_not_create_a_producer():
    app = create_app({"APP_VERSION": "test", "KAFKA_BOOTSTRAP_SERVERS": "nowhere:1"})
    assert app.test_client().get("/health").status_code == 200
    assert EXTENSION not in app.extensions


# --- GET /api/v1/sources and /api/v1/records --------------------------------------------------


def test_sources(client):
    r = client.get("/api/v1/sources")
    assert r.status_code == 200
    [source] = r.get_json()["sources"]
    assert source["source"] == "xom_ecom"
    assert source["entities"] == ["customer", "product", "region", "sales_line"]


def test_unknown_source_is_404(client):
    r = client.get("/api/v1/records?source=elsewhere")
    assert r.status_code == 404


@pytest.mark.parametrize(
    "query",
    ["page=0", "page=-1", "page=x", "page_size=0", "page_size=abc", "entity=invoice"],
)
def test_bad_paging_is_400(client, query):
    assert client.get(f"/api/v1/records?{query}").status_code == 400


@pytest.fixture
def bronze_client(scratch_warehouse):
    rows = [bronze_row(line(i), 0, i) for i in range(1, 251)]
    rows.append(bronze_row(to_envelope("customer", {"customer_id": "C-1"}, COLLECTED), 0, 1000))
    with psycopg.connect(scratch_warehouse, autocommit=True) as conn, conn.transaction():
        insert_raw_records(conn, rows)
    app = create_app({"APP_VERSION": "test", "DATABASE_URL": scratch_warehouse})
    return app.test_client()


def test_records_are_paged(bronze_client):
    r = bronze_client.get("/api/v1/records?source=xom_ecom&entity=sales_line&page_size=100")
    body = r.get_json()
    assert r.status_code == 200
    assert (body["page"], body["page_size"], body["total"], body["next_page"]) == (1, 100, 250, 2)
    first = body["records"][0]
    assert first["record_id"] == "1" and first["source_version"] == 101
    assert first["payload"]["order_id"] == "MX-2015-SC2057582-42279"

    last = bronze_client.get("/api/v1/records?entity=sales_line&page=3&page_size=100").get_json()
    assert len(last["records"]) == 50 and last["next_page"] is None
    beyond = bronze_client.get("/api/v1/records?entity=sales_line&page=9").get_json()
    assert beyond["records"] == [] and beyond["next_page"] is None


def test_page_size_defaults_to_100_and_is_capped_at_500(bronze_client):
    assert bronze_client.get("/api/v1/records").get_json()["page_size"] == 100
    body = bronze_client.get("/api/v1/records?page_size=10000").get_json()
    assert body["page_size"] == 500 and body["total"] == 251 and len(body["records"]) == 251


def test_records_endpoint_without_warehouse_is_503():
    app = create_app(
        {"APP_VERSION": "test", "DATABASE_URL": "postgresql://x@127.0.0.1:1/none?connect_timeout=1"}
    )
    r = app.test_client().get("/api/v1/records")
    assert r.status_code == 503
