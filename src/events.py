"""
Centralized event publishing over Kafka.

All publish functions are fail-safe: they return False and log a warning
when Kafka is unavailable rather than raising an exception.
"""
from datetime import datetime, timezone
from typing import Optional

from src.kafka_utils import TOPIC_CAMPAIGN_EVENTS, TOPIC_DELIVERY_EVENTS, kafka_manager


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish_campaign_event(
    event_type: str,
    campaign_id: str,
    data: Optional[dict] = None,
) -> bool:
    """Publish a campaign lifecycle event (created, dispatch_started, dispatch_completed, …)."""
    return kafka_manager.produce_message(
        TOPIC_CAMPAIGN_EVENTS,
        {
            "event_type": event_type,
            "campaign_id": campaign_id,
            "timestamp": _now_iso(),
            "data": data or {},
        },
    )


def publish_delivery_event(
    campaign_id: str,
    recipient_email: str,
    channel: str,
    delivered: bool,
    error_message: Optional[str] = None,
) -> bool:
    """Publish a per-recipient, per-channel delivery outcome event."""
    return kafka_manager.produce_message(
        TOPIC_DELIVERY_EVENTS,
        {
            "event_type": "delivery",
            "campaign_id": campaign_id,
            "recipient_email": recipient_email,
            "channel": channel,
            "delivered": delivered,
            "error_message": error_message,
            "timestamp": _now_iso(),
        },
    )
