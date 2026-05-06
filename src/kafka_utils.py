import json
import logging
from typing import Iterator

from confluent_kafka import Consumer, KafkaError, Producer

from src.config import settings

logger = logging.getLogger(__name__)

# Topic names
TOPIC_CAMPAIGN_EVENTS = "ccirp.campaign.events"
TOPIC_DELIVERY_EVENTS = "ccirp.delivery.events"


class KafkaManager:
    def __init__(self):
        self._producer_config = {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "client.id": "ccirp-producer",
            "socket.timeout.ms": 5000,
            "message.timeout.ms": 5000,
        }
        self._consumer_config = {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "ccirp-group",
            "auto.offset.reset": "earliest",
            "socket.timeout.ms": 5000,
        }
        self._producer: Producer | None = None

    def _get_producer(self) -> Producer | None:
        if self._producer is None:
            try:
                self._producer = Producer(self._producer_config)
            except Exception as exc:
                logger.warning("Kafka producer init failed: %s", exc)
        return self._producer

    def produce_message(self, topic: str, message: dict) -> bool:
        """Publish a JSON message. Returns True on success, False if Kafka is unavailable."""
        if not settings.KAFKA_ENABLED:
            return False
        producer = self._get_producer()
        if producer is None:
            return False
        try:
            producer.produce(topic, json.dumps(message).encode("utf-8"))
            producer.flush(timeout=3)
            return True
        except Exception as exc:
            logger.warning("Kafka produce failed (topic=%s): %s", topic, exc)
            self._producer = None  # reset so next call retries creation
            return False

    def consume_messages(self, topics: list[str]) -> Iterator[dict]:
        """Consume messages from topics. Yields parsed dicts. Closes consumer on exit."""
        try:
            consumer = Consumer(self._consumer_config)
        except Exception as exc:
            logger.warning("Kafka consumer init failed: %s", exc)
            return
        consumer.subscribe(topics)
        try:
            while True:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error("Kafka consumer error: %s", msg.error())
                    break
                try:
                    yield json.loads(msg.value().decode("utf-8"))
                except Exception as exc:
                    logger.warning("Kafka message parse error: %s", exc)
        finally:
            consumer.close()


kafka_manager = KafkaManager()
