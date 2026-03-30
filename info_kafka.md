# Kafka Setup and Usage

This document explains how to use Kafka for messaging in the CCIRP-be project.

## Configuration
Kafka settings are managed in `src/config.py`.
- **Bootstrap Servers**: Default: `localhost:9092`

## Utility Classes
The `KafkaManager` class in `src/kafka_utils.py` provides simple methods for producing and consuming messages.

### Producing Messages
```python
from src.kafka_utils import kafka_manager

message = {"event": "user_registered", "user_id": "123"}
kafka_manager.produce_message("user-events", message)
```

### Consuming Messages
```python
from src.kafka_utils import kafka_manager

for message in kafka_manager.consume_messages(["user-events"]):
    print(f"Received message: {message}")
    # Process message logic
```

## Running Kafka Locally
If you are using Docker, you can run Kafka using `confluentinc/cp-kafka`. Make sure it's accessible at the configured `KAFKA_BOOTSTRAP_SERVERS`.

## Best Practices
- **Topics**: Use descriptive topic names (e.g., `ccirp.notifications`, `ccirp.audit-logs`).
- **Schemas**: Consider using JSON schema or Avro for message structure (not implemented in this basic setup).
- **Error Handling**: The `KafkaManager` includes basic error handling, but for production, consider more robust retry mechanisms.
