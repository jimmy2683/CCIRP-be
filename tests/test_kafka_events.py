"""
Tests for Kafka event publishing (src/events.py and src/kafka_utils.py).

Kafka producer calls are mocked so no live broker is needed.
The tests verify payload structure, topic routing, and fail-safe behavior.
"""
import pytest
from unittest.mock import MagicMock, patch


# ── topic constants ───────────────────────────────────────────────────────────

class TestTopicConstants:
    def test_campaign_events_topic(self):
        from src.kafka_utils import TOPIC_CAMPAIGN_EVENTS

        assert TOPIC_CAMPAIGN_EVENTS == "ccirp.campaign.events"

    def test_delivery_events_topic(self):
        from src.kafka_utils import TOPIC_DELIVERY_EVENTS

        assert TOPIC_DELIVERY_EVENTS == "ccirp.delivery.events"


# ── publish_campaign_event ────────────────────────────────────────────────────

class TestPublishCampaignEvent:
    def test_sends_to_correct_topic(self, mock_kafka):
        from src.events import publish_campaign_event
        from src.kafka_utils import TOPIC_CAMPAIGN_EVENTS

        publish_campaign_event("dispatch_started", "camp_001", {"enqueued": 10})

        mock_kafka.produce_message.assert_called_once()
        topic, payload = mock_kafka.produce_message.call_args[0]
        assert topic == TOPIC_CAMPAIGN_EVENTS

    def test_payload_structure(self, mock_kafka):
        from src.events import publish_campaign_event

        publish_campaign_event("dispatch_completed", "camp_002", {"processed": 5})

        _, payload = mock_kafka.produce_message.call_args[0]
        assert payload["event_type"] == "dispatch_completed"
        assert payload["campaign_id"] == "camp_002"
        assert payload["data"]["processed"] == 5
        assert "timestamp" in payload

    def test_empty_data_defaults_to_empty_dict(self, mock_kafka):
        from src.events import publish_campaign_event

        publish_campaign_event("campaign_created", "camp_003")

        _, payload = mock_kafka.produce_message.call_args[0]
        assert payload["data"] == {}

    def test_returns_true_on_success(self, mock_kafka):
        from src.events import publish_campaign_event

        mock_kafka.produce_message.return_value = True
        result = publish_campaign_event("test_event", "camp_004")

        assert result is True

    def test_returns_false_when_kafka_unavailable(self, mock_kafka):
        from src.events import publish_campaign_event

        mock_kafka.produce_message.return_value = False
        result = publish_campaign_event("test_event", "camp_005")

        assert result is False

    def test_does_not_raise_when_kafka_unavailable(self):
        """If Kafka is completely down, publish must not raise."""
        from src.events import publish_campaign_event

        with patch("src.events.kafka_manager") as mgr:
            mgr.produce_message.return_value = False
            result = publish_campaign_event("event", "c6")

        assert result is False


# ── publish_delivery_event ────────────────────────────────────────────────────

class TestPublishDeliveryEvent:
    def test_sends_to_correct_topic(self, mock_kafka):
        from src.events import publish_delivery_event
        from src.kafka_utils import TOPIC_DELIVERY_EVENTS

        publish_delivery_event("camp_10", "alice@example.com", "email", True)

        topic, _ = mock_kafka.produce_message.call_args[0]
        assert topic == TOPIC_DELIVERY_EVENTS

    def test_payload_structure_on_success(self, mock_kafka):
        from src.events import publish_delivery_event

        publish_delivery_event("camp_11", "bob@example.com", "sms", True)

        _, payload = mock_kafka.produce_message.call_args[0]
        assert payload["event_type"] == "delivery"
        assert payload["campaign_id"] == "camp_11"
        assert payload["recipient_email"] == "bob@example.com"
        assert payload["channel"] == "sms"
        assert payload["delivered"] is True
        assert payload["error_message"] is None
        assert "timestamp" in payload

    def test_payload_structure_on_failure(self, mock_kafka):
        from src.events import publish_delivery_event

        publish_delivery_event(
            "camp_12",
            "carol@example.com",
            "email",
            False,
            "SMTP timeout",
        )

        _, payload = mock_kafka.produce_message.call_args[0]
        assert payload["delivered"] is False
        assert payload["error_message"] == "SMTP timeout"

    def test_returns_false_when_kafka_unavailable(self, mock_kafka):
        from src.events import publish_delivery_event

        mock_kafka.produce_message.return_value = False
        result = publish_delivery_event("camp_13", "dave@example.com", "whatsapp", False)

        assert result is False


# ── KafkaManager fail-safe behavior ──────────────────────────────────────────

class TestKafkaManagerFailSafe:
    def test_produce_returns_false_when_producer_init_fails(self):
        from src.kafka_utils import KafkaManager

        mgr = KafkaManager()
        with patch("src.kafka_utils.Producer", side_effect=Exception("no broker")):
            result = mgr.produce_message("some.topic", {"key": "value"})

        assert result is False

    def test_produce_returns_false_on_flush_timeout(self):
        from src.kafka_utils import KafkaManager

        mgr = KafkaManager()
        mock_producer = MagicMock()
        mock_producer.flush.side_effect = Exception("timeout")

        with patch("src.kafka_utils.Producer", return_value=mock_producer):
            result = mgr.produce_message("some.topic", {"key": "value"})

        assert result is False

    def test_produce_resets_producer_after_failure(self):
        """After a produce failure the producer is reset so the next call retries."""
        from src.kafka_utils import KafkaManager

        mgr = KafkaManager()
        mock_producer = MagicMock()
        mock_producer.flush.side_effect = Exception("network error")

        with patch("src.kafka_utils.Producer", return_value=mock_producer):
            mgr.produce_message("topic", {})
            assert mgr._producer is None  # reset after failure

    def test_produce_returns_true_on_success(self):
        from src.kafka_utils import KafkaManager

        mgr = KafkaManager()
        mock_producer = MagicMock()
        mock_producer.flush.return_value = None

        with patch("src.kafka_utils.Producer", return_value=mock_producer):
            result = mgr.produce_message("topic", {"msg": "hello"})

        assert result is True

    def test_message_is_json_serialized(self):
        """Verify the raw bytes sent to the producer are valid JSON."""
        import json

        from src.kafka_utils import KafkaManager

        mgr = KafkaManager()
        captured = {}
        mock_producer = MagicMock()

        def fake_produce(topic, value):
            captured["topic"] = topic
            captured["value"] = value

        mock_producer.produce.side_effect = fake_produce
        mock_producer.flush.return_value = None

        with patch("src.kafka_utils.Producer", return_value=mock_producer):
            mgr.produce_message("ccirp.test", {"hello": "world", "num": 42})

        assert captured["topic"] == "ccirp.test"
        parsed = json.loads(captured["value"].decode("utf-8"))
        assert parsed == {"hello": "world", "num": 42}


# ── End-to-end: delivery event published during campaign dispatch ─────────────

class TestDeliveryEventPublishedDuringDispatch:
    def test_publish_delivery_event_called_per_channel(self):
        """publish_delivery_event emits correctly structured payloads for each channel."""
        from src.events import publish_delivery_event

        published_events = []

        with patch("src.events.kafka_manager") as mock_mgr:
            mock_mgr.produce_message.side_effect = lambda topic, msg: published_events.append(
                (topic, msg)
            ) or True

            publish_delivery_event("camp_e2e", "eve@example.com", "email", True)
            publish_delivery_event("camp_e2e", "eve@example.com", "sms", False, "no phone")

        delivery = [e for _, e in published_events if e.get("event_type") == "delivery"]
        assert len(delivery) == 2
        assert delivery[0]["channel"] == "email"
        assert delivery[0]["delivered"] is True
        assert delivery[1]["channel"] == "sms"
        assert delivery[1]["delivered"] is False
        assert delivery[1]["error_message"] == "no phone"
