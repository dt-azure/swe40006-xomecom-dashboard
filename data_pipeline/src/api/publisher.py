"""Kafka publishing for POST /api/v1/records.

The producer is created on first use (never at import or app start), so /health and the read
endpoints work while Kafka is down, and each gunicorn worker builds its own after the fork.
Settings: acks=all and idempotence on, and every publish waits for the broker's acknowledgement
of each record (flush) before the API answers. A record that is not acknowledged raises
PublishError, which the API turns into 503.
"""

import json
import logging
import threading

from flask import current_app

log = logging.getLogger(__name__)

EXTENSION = "kafka_publisher"


class PublishError(Exception):
    pass


class KafkaPublisher:
    def __init__(self, bootstrap_servers, topic, timeout_seconds=15.0, producer_factory=None):
        self.topic = topic
        self.timeout = timeout_seconds
        self._config = {
            "bootstrap.servers": bootstrap_servers,
            "acks": "all",
            "enable.idempotence": True,
            "linger.ms": 5,
            "compression.type": "lz4",
            # Give up on a record well inside the HTTP timeout, so the caller gets a 503 rather
            # than a hung request.
            "message.timeout.ms": int(timeout_seconds * 1000 * 2 / 3),
            "request.timeout.ms": 5000,
        }
        self._factory = producer_factory
        self._producer = None
        self._lock = threading.Lock()

    def _get_producer(self):
        if self._producer is None:
            if self._factory is not None:
                self._producer = self._factory(self._config)
            else:
                from confluent_kafka import Producer

                self._producer = Producer(self._config)
        return self._producer

    def publish(self, messages):
        """Publish (key, record) pairs and wait until every one is acknowledged or failed."""
        errors = []

        def on_delivery(err, _msg):
            if err is not None:
                errors.append(str(err))

        with self._lock:  # one flush at a time per worker; flush covers the whole producer
            try:
                producer = self._get_producer()
                for key, record in messages:
                    value = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    while True:
                        try:
                            producer.produce(
                                self.topic,
                                key=key.encode("utf-8"),
                                value=value.encode("utf-8"),
                                on_delivery=on_delivery,
                            )
                            break
                        except BufferError:  # local queue full: let it drain, then retry
                            producer.poll(0.5)
                remaining = producer.flush(self.timeout)
            except Exception as e:  # KafkaException, bad config, ...
                raise PublishError(f"publish failed: {e}") from e
        if remaining:
            raise PublishError(f"{remaining} record(s) not acknowledged within {self.timeout}s")
        if errors:
            raise PublishError(f"{len(errors)} record(s) failed: {errors[0]}")


def get_publisher():
    app = current_app
    publisher = app.extensions.get(EXTENSION)
    if publisher is None:
        publisher = KafkaPublisher(
            app.config["KAFKA_BOOTSTRAP_SERVERS"],
            app.config["KAFKA_TOPIC"],
            timeout_seconds=float(app.config["KAFKA_PUBLISH_TIMEOUT_SECONDS"]),
        )
        app.extensions[EXTENSION] = publisher
    return publisher
