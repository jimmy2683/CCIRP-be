# Kafka Setup and Usage

This document explains how to use Kafka for messaging in the CCIRP-be project.

## Configuration
Kafka settings are managed in `src/config.py`.
- **Bootstrap Servers**: Default: `localhost:9092`

## Topics
Topic name constants are defined in `src/kafka_utils.py`:
```python
TOPIC_CAMPAIGN_EVENTS = "ccirp.campaign.events"   # campaign lifecycle events
TOPIC_DELIVERY_EVENTS = "ccirp.delivery.events"   # per-recipient delivery outcomes
```

## Publishing Events
Use the helper functions in `src/events.py` rather than calling `KafkaManager` directly:

```python
from src.events import publish_campaign_event, publish_delivery_event

# Campaign lifecycle
publish_campaign_event("dispatch_started", campaign_id, {"enqueued": 10})
publish_campaign_event("dispatch_completed", campaign_id, {"processed": 10})

# Per-recipient delivery outcome
publish_delivery_event(
    campaign_id=campaign_id,
    recipient_email="alice@example.com",
    channel="email",
    delivered=True,
    error_message=None,   # set on failure
)
```

Both functions return `True` on success and `False` if Kafka is unavailable — they never raise.

## KafkaManager (low-level)
`KafkaManager` in `src/kafka_utils.py` is a fail-safe producer wrapper:
- Creates a new `confluent_kafka.Producer` on first use (lazy init).
- Catches all exceptions from `produce()` and `flush()`, resets `_producer` to `None`, and returns `False` so the app never crashes on Kafka unavailability.
- Messages are JSON-serialized before sending.

```python
from src.kafka_utils import kafka_manager

result = kafka_manager.produce_message("ccirp.campaign.events", {"key": "value"})
# result is True on success, False on any failure
```

> **Note**: `KafkaManager` is produce-only. There is no consumer implementation.

## Running Kafka Locally
If you are using Docker, you can run Kafka using `confluentinc/cp-kafka`. Make sure it's accessible at the configured `KAFKA_BOOTSTRAP_SERVERS`.

## Best Practices
- **Use helpers**: Prefer `publish_campaign_event` / `publish_delivery_event` over calling `kafka_manager` directly — they handle payload structure and timestamps.
- **Fail-safe**: Kafka being down must never block the main request path. The producer returns `False` silently; log or alert separately if needed.
- **Topics**: Use the constants from `kafka_utils.py` — don't hardcode topic strings.
