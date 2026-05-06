# Kafka Setup and Usage

This document explains how Kafka is used for event publishing in CCIRP-be.

## Configuration

Kafka settings are managed in `src/config.py`:

| Setting | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | |
| `KAFKA_ENABLED` | `True` | **Set to `False` in `.env` when Kafka is not running** |

### Running Without Kafka

If Kafka is not available, set `KAFKA_ENABLED=False` in `.env`. When disabled, `produce_message` returns `False` immediately without creating a `Producer`. This prevents librdkafka from spawning its background reconnect thread, which otherwise floods logs with:

```
FAIL | localhost:9092/bootstrap: Connect to ipv4#127.0.0.1:9092 failed: Connection refused
```

## Topics

Topic name constants are defined in `src/kafka_utils.py`:

```python
TOPIC_CAMPAIGN_EVENTS = "ccirp.campaign.events"   # campaign lifecycle events
TOPIC_DELIVERY_EVENTS = "ccirp.delivery.events"   # per-recipient delivery outcomes
```

## Publishing Events

Use the helper functions in `src/events.py` — do not call `KafkaManager` directly:

```python
from src.events import publish_campaign_event, publish_delivery_event

# Campaign lifecycle
publish_campaign_event("campaign_created", campaign_id, {"name": "...", "status": "queued"})
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

Both functions return `True` on success and `False` if Kafka is unavailable or disabled — they never raise.

## KafkaManager (low-level)

`KafkaManager` in `src/kafka_utils.py` is a fail-safe producer wrapper:

- Checks `settings.KAFKA_ENABLED` first — if `False`, returns immediately.
- Creates a `confluent_kafka.Producer` lazily on first use.
- On any exception from `produce()` or `flush()`, resets `_producer` to `None` and returns `False`.

```python
from src.kafka_utils import kafka_manager

result = kafka_manager.produce_message("ccirp.campaign.events", {"key": "value"})
# True on success, False on failure or when KAFKA_ENABLED=False
```

> **Note**: `KafkaManager` is produce-only. There is no consumer implementation.

## Running Kafka Locally

Using Docker:

```bash
docker run -d --name ccirp-kafka \
  -p 9092:9092 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  confluentinc/cp-kafka
```

Once running, remove or set `KAFKA_ENABLED=True` in `.env` and restart the backend.

## Best Practices

- **Use helpers**: Prefer `publish_campaign_event` / `publish_delivery_event` over calling `kafka_manager` directly.
- **Fail-safe**: Kafka being down must never block the main request path.
- **Topics**: Always use the constants from `kafka_utils.py` — do not hardcode topic strings.
- **Disabled by default in dev**: Keep `KAFKA_ENABLED=False` in `.env` during local development unless actively working on event pipeline features.
