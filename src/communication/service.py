import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from pymongo import ReturnDocument, UpdateOne

from src.communication.messaging_service import MessagingService, html_to_text
from src.communication.tracking_service import ensure_recipient_stats, record_delivery_event
from src.communication.tracking_utils import inject_tracking
from src.config import settings
from src.database import get_database


ALLOWED_CAMPAIGN_CHANNELS = ("email", "sms", "whatsapp")
PRIORITY_QUEUE_ORDER = ("critical", "high", "medium", "low")
PRIORITY_QUEUE_RANK = {level: index for index, level in enumerate(PRIORITY_QUEUE_ORDER)}
PRIORITY_ALGORITHM_VERSION = "v1"
_queue_indexes_ready = False


def normalize_campaign_channels(channels: Iterable[str]) -> List[str]:
    normalized = []
    seen = set()

    for channel in channels or []:
        clean_channel = str(channel).strip().lower()
        if clean_channel not in ALLOWED_CAMPAIGN_CHANNELS or clean_channel in seen:
            continue
        seen.add(clean_channel)
        normalized.append(clean_channel)

    return normalized or ["email"]


def render_campaign_content(body_html: str, merge_data: dict, recipient_email: str, recipient_data: dict) -> str:
    rendered = body_html
    all_fields = dict(merge_data)

    all_fields["email"] = recipient_email
    all_fields["recipient_email"] = recipient_email
    full_name = recipient_data.get("full_name", recipient_email.split("@")[0])
    all_fields["name"] = full_name
    all_fields["full_name"] = full_name
    all_fields["recipient_name"] = full_name
    all_fields["first_name"] = full_name.split(" ")[0] if full_name else ""

    for key, value in all_fields.items():
        rendered = re.sub(
            r"\{\{\s*" + re.escape(key) + r"\s*\}\}",
            str(value),
            rendered,
            flags=re.IGNORECASE,
        )

    return rendered


def _normalize_tag_key(tag: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tag).strip().lower()).strip("_")
    return normalized or "untagged"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _days_since(reference: Optional[datetime], now: datetime) -> Optional[float]:
    if not reference:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max((now - reference).total_seconds() / 86400, 0.0)


def _priority_level_for_score(score: float) -> str:
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 28:
        return "medium"
    return "low"


def _batch_size_for_level(level: str) -> int:
    if level == "critical":
        return max(settings.CAMPAIGN_QUEUE_BATCH_SIZE_CRITICAL, 1)
    if level == "high":
        return max(settings.CAMPAIGN_QUEUE_BATCH_SIZE_HIGH, 1)
    if level == "medium":
        return max(settings.CAMPAIGN_QUEUE_BATCH_SIZE_MEDIUM, 1)
    return max(settings.CAMPAIGN_QUEUE_BATCH_SIZE_LOW, 1)


async def _ensure_campaign_queue_indexes(db) -> None:
    global _queue_indexes_ready
    if _queue_indexes_ready:
        return

    await db["campaign_dispatch_queue"].create_index(
        [("campaign_id", 1), ("recipient_email", 1)],
        unique=True,
        name="campaign_recipient_unique",
    )
    await db["campaign_dispatch_queue"].create_index(
        [("status", 1), ("available_at", 1), ("priority_level_rank", 1), ("priority_score", -1), ("created_at", 1)],
        name="queue_processing_lookup",
    )
    await db["campaign_dispatch_queue"].create_index(
        [("campaign_id", 1), ("status", 1)],
        name="campaign_status_lookup",
    )
    await db["campaign_dispatch_queue"].create_index(
        [("status", 1), ("processing_started_at", 1)],
        name="stale_processing_lookup",
    )
    _queue_indexes_ready = True


async def _ensure_audience_recipients(
    *,
    db,
    owner_user_id: str,
    recipients: List[str],
    recipient_data_map: Dict[str, dict],
) -> Dict[str, dict]:
    existing_recips = await db["recipients"].find(
        {"user_id": owner_user_id, "email": {"$in": recipients}}
    ).to_list(length=1000)
    recipient_map = {recipient["email"]: recipient for recipient in existing_recips}

    new_recipients = []
    now = datetime.now(timezone.utc)
    for email in recipients:
        if email in recipient_map:
            continue

        user_data = recipient_data_map.get(email, {})
        full_name = user_data.get("full_name", email.split("@")[0])
        first_name = full_name.split(" ")[0] if full_name else email.split("@")[0]
        last_name = full_name.split(" ", 1)[1] if " " in full_name else None
        recipient_doc = {
            "user_id": owner_user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "phone": user_data.get("phone"),
            "tags": ["auto-added", "user-synced"] if user_data.get("phone") else ["auto-added"],
            "attributes": {},
            "consent_flags": {"email": True, "sms": False, "whatsapp": False},
            "status": "active",
            "engagement": {
                "open_count_total": 0,
                "click_count_total": 0,
                "unique_open_campaigns": [],
                "unique_click_campaigns": [],
                "clicked_domains": [],
                "tag_scores": {},
                "topic_scores": {},
                "last_open_at": None,
                "last_click_at": None,
            },
            "created_at": now,
            "updated_at": now,
        }
        new_recipients.append(recipient_doc)
        recipient_map[email] = recipient_doc

    if new_recipients:
        await db["recipients"].insert_many(new_recipients)

    for email, recipient in recipient_map.items():
        user_data = recipient_data_map.get(email)
        if not user_data:
            continue

        full_name = user_data.get("full_name", "").strip()
        first_name = full_name.split(" ")[0] if full_name else recipient.get("first_name", email.split("@")[0])
        last_name = full_name.split(" ", 1)[1] if " " in full_name else recipient.get("last_name")
        phone = user_data.get("phone") or recipient.get("phone")
        await db["recipients"].update_one(
            {"user_id": owner_user_id, "email": email},
            {
                "$set": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        recipient["first_name"] = first_name
        recipient["last_name"] = last_name
        recipient["phone"] = phone

    return recipient_map


def _channel_ready(channel: str, recipient_doc: Optional[dict]) -> tuple[bool, str]:
    if channel == "email":
        return True, ""

    if not recipient_doc:
        return False, f"Recipient record is required for {channel}"

    if not recipient_doc.get("phone"):
        return False, f"Recipient is missing a phone number for {channel}"

    return True, ""


async def _send_channel_message(
    *,
    channel: str,
    recipient_email: str,
    recipient_doc: Optional[dict],
    subject: str,
    rendered_html: str,
    rendered_text: str,
    campaign_id: str,
    owner_user_id: str,
) -> tuple[bool, str]:
    allowed, reason = _channel_ready(channel, recipient_doc)
    if not allowed:
        return False, reason

    if channel == "email":
        tracked_body = inject_tracking(
            rendered_html,
            campaign_id,
            recipient_email,
            owner_user_id,
            settings.TRACKING_BASE_URL,
        )
        return await MessagingService.send_email(recipient_email, subject, tracked_body)

    if channel == "sms":
        return await MessagingService.send_sms(recipient_doc.get("phone"), rendered_text)

    if channel == "whatsapp":
        return await MessagingService.send_whatsapp(recipient_doc.get("phone"), rendered_text)

    return False, f"Unsupported channel: {channel}"


def _campaign_query(campaign_id: str) -> dict:
    try:
        return {"_id": ObjectId(campaign_id)}
    except Exception:
        return {"_id": campaign_id}


async def _get_recipient_history_map(
    *,
    db,
    owner_user_id: str,
    recipients: List[str],
) -> Dict[str, dict]:
    if not recipients:
        return {}

    pipeline = [
        {
            "$match": {
                "owner_user_id": owner_user_id,
                "recipient_email": {"$in": recipients},
            }
        },
        {
            "$group": {
                "_id": "$recipient_email",
                "campaign_touchpoints": {"$sum": 1},
                "delivery_count": {"$sum": {"$ifNull": ["$delivery_count", 0]}},
                "delivery_failure_count": {"$sum": {"$ifNull": ["$delivery_failure_count", 0]}},
                "open_count": {"$sum": {"$ifNull": ["$open_count", 0]}},
                "click_count": {"$sum": {"$ifNull": ["$click_count", 0]}},
                "unique_open_count": {"$sum": {"$ifNull": ["$unique_open_count", 0]}},
                "unique_click_count": {"$sum": {"$ifNull": ["$unique_click_count", 0]}},
                "last_delivered_at": {"$max": "$last_delivered_at"},
                "last_delivery_failed_at": {"$max": "$last_delivery_failed_at"},
                "last_open_at": {"$max": "$last_open_at"},
                "last_click_at": {"$max": "$last_click_at"},
            }
        },
    ]

    results = await db["campaign_recipient_stats"].aggregate(pipeline).to_list(length=len(recipients))
    history_map = {}
    for row in results:
        history_map[str(row["_id"])] = row
    return history_map


def _calculate_recipient_priority(
    *,
    recipient_email: str,
    recipient_doc: Optional[dict],
    campaign_tags: List[str],
    channels: List[str],
    history_stats: Optional[dict],
) -> dict:
    # Weighted priority model:
    # - recent opens/clicks raise urgency
    # - clicks matter more than opens because they indicate stronger intent
    # - campaign-tag affinity boosts recipients who historically engage with similar content
    # - repeated historical touchpoints increase confidence that the recipient is active
    # - delivery failures, inactive status, missing consent, or missing channel readiness reduce score
    now = datetime.now(timezone.utc)
    recipient_doc = recipient_doc or {}
    history_stats = history_stats or {}
    engagement = recipient_doc.get("engagement") or {}
    consent_flags = recipient_doc.get("consent_flags") or {}

    open_count_total = int(engagement.get("open_count_total") or 0)
    click_count_total = int(engagement.get("click_count_total") or 0)
    unique_open_campaigns = engagement.get("unique_open_campaigns") or []
    unique_click_campaigns = engagement.get("unique_click_campaigns") or []
    recipient_tags = {str(tag).strip().lower() for tag in recipient_doc.get("tags") or [] if str(tag).strip()}
    campaign_tag_keys = [_normalize_tag_key(tag) for tag in campaign_tags]
    engagement_tag_scores = engagement.get("tag_scores") or {}

    last_click_at = engagement.get("last_click_at") or history_stats.get("last_click_at")
    last_open_at = engagement.get("last_open_at") or history_stats.get("last_open_at")
    most_recent_touch = max(
        [value for value in [last_click_at, last_open_at] if value],
        default=None,
    )
    recency_days = _days_since(most_recent_touch, now)

    tag_affinity_raw = sum(int(engagement_tag_scores.get(tag_key, 0) or 0) for tag_key in campaign_tag_keys)
    direct_tag_overlap = len(recipient_tags.intersection({str(tag).strip().lower() for tag in campaign_tags if str(tag).strip()}))
    campaign_touchpoints = int(history_stats.get("campaign_touchpoints") or 0)
    delivery_count = int(history_stats.get("delivery_count") or 0)
    delivery_failure_count = int(history_stats.get("delivery_failure_count") or 0)
    requested_non_email_channels = [channel for channel in channels if channel != "email"]

    open_points = min(math.log1p(open_count_total) / math.log1p(20), 1.0) * 16
    click_points = min(
        math.log1p(click_count_total + (len(unique_click_campaigns) * 2)) / math.log1p(18),
        1.0,
    ) * 22
    relationship_points = min(math.log1p(campaign_touchpoints) / math.log1p(12), 1.0) * 8
    tag_affinity_points = min(tag_affinity_raw / 6, 1.0) * 16
    direct_tag_points = min(direct_tag_overlap / 3, 1.0) * 8

    if recency_days is None:
        recency_points = 0.0
    elif recency_days <= 3:
        recency_points = 16.0
    elif recency_days <= 7:
        recency_points = 12.0
    elif recency_days <= 14:
        recency_points = 9.0
    elif recency_days <= 30:
        recency_points = 6.0
    elif recency_days <= 90:
        recency_points = 3.0
    else:
        recency_points = 0.0

    total_delivery_attempts = max(delivery_count + delivery_failure_count, 0)
    if total_delivery_attempts > 0:
        reliability_ratio = delivery_count / total_delivery_attempts
        reliability_points = reliability_ratio * 6
    else:
        reliability_points = 3.0

    status_points = 5.0 if str(recipient_doc.get("status", "active")).lower() == "active" else -20.0

    consent_penalty = 0.0
    if "email" in channels and consent_flags.get("email") is False:
        consent_penalty -= 15.0
    if "sms" in channels and consent_flags.get("sms") is False:
        consent_penalty -= 6.0
    if "whatsapp" in channels and consent_flags.get("whatsapp") is False:
        consent_penalty -= 6.0

    if requested_non_email_channels:
        channel_readiness_points = 5.0 if recipient_doc.get("phone") else -6.0
    else:
        channel_readiness_points = 3.0

    score = open_points + click_points + relationship_points + tag_affinity_points
    score += direct_tag_points + recency_points + reliability_points + status_points
    score += consent_penalty + channel_readiness_points
    score = _clamp(score, 0.0, 100.0)

    priority_level = _priority_level_for_score(score)
    breakdown = {
        "open_history_weight": round(open_points, 2),
        "click_history_weight": round(click_points, 2),
        "relationship_weight": round(relationship_points, 2),
        "tag_affinity_weight": round(tag_affinity_points, 2),
        "direct_tag_match_weight": round(direct_tag_points, 2),
        "recency_weight": round(recency_points, 2),
        "reliability_weight": round(reliability_points, 2),
        "status_weight": round(status_points, 2),
        "consent_weight": round(consent_penalty, 2),
        "channel_readiness_weight": round(channel_readiness_points, 2),
        "historical_campaign_touchpoints": campaign_touchpoints,
        "recipient_email": recipient_email,
        "algorithm_version": PRIORITY_ALGORITHM_VERSION,
    }

    return {
        "priority_score": round(score, 2),
        "priority_level": priority_level,
        "priority_level_rank": PRIORITY_QUEUE_RANK[priority_level],
        "priority_breakdown": breakdown,
    }


async def _sync_campaign_queue_state(campaign_id: str) -> None:
    db = get_database()
    if db is None:
        return

    pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                "queued": {"$sum": {"$cond": [{"$eq": ["$status", "queued"]}, 1, 0]}},
                "processing": {"$sum": {"$cond": [{"$eq": ["$status", "processing"]}, 1, 0]}},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
                "cancelled": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}},
                "sent_outcomes": {"$sum": {"$cond": [{"$eq": ["$delivery_outcome", "sent"]}, 1, 0]}},
                "partial_outcomes": {"$sum": {"$cond": [{"$eq": ["$delivery_outcome", "partially_sent"]}, 1, 0]}},
                "failed_outcomes": {"$sum": {"$cond": [{"$eq": ["$delivery_outcome", "failed"]}, 1, 0]}},
                "critical": {"$sum": {"$cond": [{"$eq": ["$priority_level", "critical"]}, 1, 0]}},
                "high": {"$sum": {"$cond": [{"$eq": ["$priority_level", "high"]}, 1, 0]}},
                "medium": {"$sum": {"$cond": [{"$eq": ["$priority_level", "medium"]}, 1, 0]}},
                "low": {"$sum": {"$cond": [{"$eq": ["$priority_level", "low"]}, 1, 0]}},
                "channel_attempts": {"$sum": {"$ifNull": ["$channel_attempts", 0]}},
                "channel_failures": {"$sum": {"$ifNull": ["$channel_failures", 0]}},
            }
        },
    ]
    summary_rows = await db["campaign_dispatch_queue"].aggregate(pipeline).to_list(length=1)
    if not summary_rows:
        return

    summary = summary_rows[0]
    next_queued_job = await db["campaign_dispatch_queue"].find_one(
        {"campaign_id": campaign_id, "status": "queued"},
        sort=[("available_at", 1)],
        projection={"available_at": 1},
    )
    campaign = await db["campaigns"].find_one(_campaign_query(campaign_id))
    if not campaign:
        return

    now = datetime.now(timezone.utc)
    next_status = campaign.get("status", "draft")
    if summary["processing"] > 0 or summary["completed"] > 0 or summary["failed"] > 0:
        if summary["queued"] == 0 and summary["processing"] == 0:
            successful_jobs = summary["sent_outcomes"] + summary["partial_outcomes"]
            if successful_jobs == 0:
                next_status = "failed"
            elif summary["failed_outcomes"] == 0:
                next_status = "sent"
            else:
                next_status = "partially_sent"
        else:
            next_status = "dispatching"
    elif campaign.get("scheduled_at") and campaign["scheduled_at"] > now:
        next_status = "scheduled"
    elif summary["queued"] > 0:
        next_status = "queued"

    update_fields = {
        "status": next_status,
        "queue_summary": {
            "algorithm_version": PRIORITY_ALGORITHM_VERSION,
            "total": summary["total"],
            "queued": summary["queued"],
            "processing": summary["processing"],
            "completed": summary["completed"],
            "failed": summary["failed"],
            "cancelled": summary["cancelled"],
            "levels": {
                "critical": summary["critical"],
                "high": summary["high"],
                "medium": summary["medium"],
                "low": summary["low"],
            },
            "next_available_at": next_queued_job.get("available_at") if next_queued_job else None,
        },
        "delivery_summary": {
            "total_attempts": summary["channel_attempts"],
            "failed_attempts": summary["channel_failures"],
            "successful_attempts": max(summary["channel_attempts"] - summary["channel_failures"], 0),
        },
        "updated_at": now,
    }

    if next_status == "dispatching" and not campaign.get("dispatch_started_at"):
        update_fields["dispatch_started_at"] = now
    if next_status in {"sent", "partially_sent", "failed"}:
        update_fields["dispatch_completed_at"] = now

    await db["campaigns"].update_one(_campaign_query(campaign_id), {"$set": update_fields})


async def enqueue_campaign_recipients(campaign_id: str) -> int:
    db = get_database()
    if db is None:
        return 0

    await _ensure_campaign_queue_indexes(db)
    campaign = await db["campaigns"].find_one(_campaign_query(campaign_id))
    if not campaign:
        return 0

    recipients = campaign.get("recipients", [])
    if not recipients:
        return 0

    recipient_data_map: Dict[str, dict] = {}
    users_list = await db["users"].find({"email": {"$in": recipients}}).to_list(length=1000)
    if users_list:
        recipient_data_map = {user["email"]: user for user in users_list}

    recipient_records = await _ensure_audience_recipients(
        db=db,
        owner_user_id=campaign["created_by"],
        recipients=recipients,
        recipient_data_map=recipient_data_map,
    )
    history_map = await _get_recipient_history_map(
        db=db,
        owner_user_id=campaign["created_by"],
        recipients=recipients,
    )

    available_at = campaign.get("scheduled_at") or datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    bulk_operations = []
    for recipient_email in recipients:
        priority = _calculate_recipient_priority(
            recipient_email=recipient_email,
            recipient_doc=recipient_records.get(recipient_email),
            campaign_tags=campaign.get("tags", []),
            channels=campaign.get("channels", ["email"]),
            history_stats=history_map.get(recipient_email),
        )
        bulk_operations.append(
            UpdateOne(
                {"campaign_id": campaign_id, "recipient_email": recipient_email},
                {
                    "$setOnInsert": {
                        "campaign_id": campaign_id,
                        "owner_user_id": campaign["created_by"],
                        "recipient_email": recipient_email,
                        "channels": campaign.get("channels", ["email"]),
                        "available_at": available_at,
                        "status": "queued",
                        "attempts": 0,
                        "priority_score": priority["priority_score"],
                        "priority_level": priority["priority_level"],
                        "priority_level_rank": priority["priority_level_rank"],
                        "priority_breakdown": priority["priority_breakdown"],
                        "delivery_outcome": None,
                        "channel_attempts": 0,
                        "channel_failures": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )
        )

    inserted_count = 0
    if bulk_operations:
        result = await db["campaign_dispatch_queue"].bulk_write(bulk_operations, ordered=False)
        inserted_count = result.upserted_count

    await db["campaigns"].update_one(
        _campaign_query(campaign_id),
        {
            "$set": {
                "queue_prepared_at": now,
                "priority_algorithm_version": PRIORITY_ALGORITHM_VERSION,
            }
        },
    )
    await _sync_campaign_queue_state(campaign_id)
    return inserted_count


async def prepare_campaign_priority_dispatch(campaign_id: str, kickoff_processing: bool = False) -> None:
    await enqueue_campaign_recipients(campaign_id)
    if kickoff_processing:
        await process_campaign_priority_queues_once(campaign_id=campaign_id)


async def _requeue_stale_processing_jobs_once() -> int:
    db = get_database()
    if db is None:
        return 0

    await _ensure_campaign_queue_indexes(db)
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=max(settings.CAMPAIGN_QUEUE_STALE_SECONDS, 60))
    result = await db["campaign_dispatch_queue"].update_many(
        {
            "status": "processing",
            "processing_started_at": {"$lte": stale_before},
        },
        {
            "$set": {
                "status": "queued",
                "updated_at": datetime.now(timezone.utc),
            },
            "$unset": {
                "processing_started_at": "",
            },
        },
    )
    return result.modified_count


async def _prepare_pending_campaign_queues_once(limit: int = 10) -> int:
    db = get_database()
    if db is None:
        return 0

    cursor = db["campaigns"].find(
        {
            "status": {"$in": ["queued", "scheduled", "dispatching"]},
            "recipients": {"$exists": True, "$ne": []},
            "queue_prepared_at": {"$exists": False},
        }
    ).sort("created_at", 1).limit(limit)

    campaigns = await cursor.to_list(length=limit)
    prepared = 0
    for campaign in campaigns:
        await enqueue_campaign_recipients(str(campaign["_id"]))
        prepared += 1
    return prepared


async def _claim_next_priority_job(
    *,
    level: str,
    now: datetime,
    campaign_id: Optional[str] = None,
) -> Optional[dict]:
    db = get_database()
    if db is None:
        return None

    query = {
        "status": "queued",
        "priority_level": level,
        "available_at": {"$lte": now},
    }
    if campaign_id:
        query["campaign_id"] = campaign_id

    return await db["campaign_dispatch_queue"].find_one_and_update(
        query,
        {
            "$set": {
                "status": "processing",
                "processing_started_at": now,
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
        },
        sort=[("priority_score", -1), ("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _mark_queue_job_terminal(
    *,
    queue_job_id: Any,
    campaign_id: str,
    status: str,
    delivery_outcome: str,
    channel_attempts: int,
    channel_failures: int,
    channel_results: List[dict],
    error_message: Optional[str] = None,
) -> None:
    db = get_database()
    if db is None:
        return

    now = datetime.now(timezone.utc)
    await db["campaign_dispatch_queue"].update_one(
        {"_id": queue_job_id},
        {
            "$set": {
                "status": status,
                "delivery_outcome": delivery_outcome,
                "completed_at": now,
                "updated_at": now,
                "channel_attempts": channel_attempts,
                "channel_failures": channel_failures,
                "channel_results": channel_results,
                "error_message": error_message,
            },
            "$unset": {
                "processing_started_at": "",
            },
        },
    )
    await _sync_campaign_queue_state(campaign_id)


async def _process_priority_queue_job(job: dict) -> None:
    db = get_database()
    if db is None:
        return

    campaign_id = str(job["campaign_id"])
    campaign = await db["campaigns"].find_one(_campaign_query(campaign_id))
    if not campaign:
        await _mark_queue_job_terminal(
            queue_job_id=job["_id"],
            campaign_id=campaign_id,
            status="cancelled",
            delivery_outcome="failed",
            channel_attempts=0,
            channel_failures=0,
            channel_results=[],
            error_message="Campaign no longer exists",
        )
        return

    template = None
    try:
        template = await db["templates"].find_one({"_id": ObjectId(campaign["template_id"])})
    except Exception:
        template = await db["templates"].find_one({"_id": campaign["template_id"]})

    if not template:
        await _mark_queue_job_terminal(
            queue_job_id=job["_id"],
            campaign_id=campaign_id,
            status="failed",
            delivery_outcome="failed",
            channel_attempts=0,
            channel_failures=0,
            channel_results=[],
            error_message="Template not found",
        )
        return

    recipient_email = job["recipient_email"]
    channels = normalize_campaign_channels(campaign.get("channels", []))

    recipient_doc = await db["recipients"].find_one(
        {"user_id": campaign["created_by"], "email": recipient_email}
    )
    user_data = await db["users"].find_one({"email": recipient_email}) or {}

    rendered_html = render_campaign_content(
        template.get("body_html", ""),
        campaign.get("merge_data") or {},
        recipient_email,
        user_data,
    )
    rendered_text = html_to_text(rendered_html)
    subject = campaign.get("subject") or template.get("subject", "No Subject")

    if campaign.get("status") not in {"dispatching", "sent", "partially_sent", "failed"}:
        await db["campaigns"].update_one(
            _campaign_query(campaign_id),
            {
                "$set": {
                    "status": "dispatching",
                    "dispatch_started_at": datetime.now(timezone.utc),
                }
            },
        )

    channel_results = []
    channel_attempts = 0
    channel_failures = 0
    for channel in channels:
        channel_attempts += 1
        await ensure_recipient_stats(
            db=db,
            campaign_id=campaign_id,
            recipient_email=recipient_email,
            owner_user_id=campaign["created_by"],
            channel=channel,
        )

        success, message = await _send_channel_message(
            channel=channel,
            recipient_email=recipient_email,
            recipient_doc=recipient_doc,
            subject=subject,
            rendered_html=rendered_html,
            rendered_text=rendered_text,
            campaign_id=campaign_id,
            owner_user_id=campaign["created_by"],
        )
        await record_delivery_event(
            db=db,
            campaign_id=campaign_id,
            recipient_email=recipient_email,
            owner_user_id=campaign["created_by"],
            delivered=success,
            error_message=None if success else message,
            channel=channel,
        )

        if not success:
            channel_failures += 1

        channel_results.append(
            {
                "channel": channel,
                "success": success,
                "message": message,
            }
        )

    if channel_attempts == 0:
        status = "failed"
        delivery_outcome = "failed"
        error_message = "No channels available for dispatch"
    elif channel_failures == 0:
        status = "completed"
        delivery_outcome = "sent"
        error_message = None
    elif channel_failures < channel_attempts:
        status = "completed"
        delivery_outcome = "partially_sent"
        error_message = None
    else:
        status = "failed"
        delivery_outcome = "failed"
        error_message = "All channel attempts failed"

    await _mark_queue_job_terminal(
        queue_job_id=job["_id"],
        campaign_id=campaign_id,
        status=status,
        delivery_outcome=delivery_outcome,
        channel_attempts=channel_attempts,
        channel_failures=channel_failures,
        channel_results=channel_results,
        error_message=error_message,
    )


async def process_campaign_priority_queues_once(campaign_id: Optional[str] = None) -> int:
    db = get_database()
    if db is None:
        return 0

    await _ensure_campaign_queue_indexes(db)
    now = datetime.now(timezone.utc)
    processed = 0

    for level in PRIORITY_QUEUE_ORDER:
        batch_size = _batch_size_for_level(level)
        for _ in range(batch_size):
            queue_job = await _claim_next_priority_job(level=level, now=now, campaign_id=campaign_id)
            if not queue_job:
                break
            await _process_priority_queue_job(queue_job)
            processed += 1

    return processed


async def dispatch_campaign_by_id(campaign_id: str) -> None:
    await enqueue_campaign_recipients(campaign_id)
    while True:
        processed = await process_campaign_priority_queues_once(campaign_id=campaign_id)
        if processed == 0:
            break


async def run_campaign_scheduler(stop_event: asyncio.Event) -> None:
    interval_seconds = max(settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS, 5)

    while not stop_event.is_set():
        try:
            await _prepare_pending_campaign_queues_once()
            await _requeue_stale_processing_jobs_once()
            await process_campaign_priority_queues_once()
        except Exception as exc:
            print(f"Campaign scheduler error: {exc}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
