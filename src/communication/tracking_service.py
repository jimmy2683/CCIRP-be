from datetime import datetime, timezone
import re
from typing import Optional
from urllib.parse import urlparse

from bson import ObjectId


async def _get_campaign_tags(db, campaign_id: str) -> list[str]:
    try:
        query = {"_id": ObjectId(campaign_id)}
    except Exception:
        query = {"_id": campaign_id}

    campaign = await db["campaigns"].find_one(query, {"tags": 1})
    raw_tags = campaign.get("tags", []) if campaign else []

    normalized_tags = []
    seen = set()
    for tag in raw_tags:
        clean_tag = str(tag).strip()
        if not clean_tag:
            continue
        key = clean_tag.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_tags.append(clean_tag)
    return normalized_tags


def _tag_score_key(tag: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", tag.strip().lower()).strip("_")
    return normalized or "untagged"


def _recipient_stats_defaults(
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    now: datetime,
) -> dict:
    return {
        "campaign_id": campaign_id,
        "recipient_email": recipient_email,
        "owner_user_id": owner_user_id,
        "campaign_tags": [],
        "delivery_status": "pending",
        "delivery_count": 0,
        "delivery_failure_count": 0,
        "open_count": 0,
        "click_count": 0,
        "unique_open_count": 0,
        "unique_click_count": 0,
        "created_at": now,
    }


async def ensure_recipient_stats(
    *,
    db,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    campaign_tags = await _get_campaign_tags(db, campaign_id)
    await db["campaign_recipient_stats"].update_one(
        {"campaign_id": campaign_id, "recipient_email": recipient_email},
        {
            "$setOnInsert": _recipient_stats_defaults(
                campaign_id, recipient_email, owner_user_id, now
            ),
            "$set": {
                "owner_user_id": owner_user_id,
                "campaign_tags": campaign_tags,
                "updated_at": now,
            },
        },
        upsert=True,
    )


async def record_delivery_event(
    *,
    db,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    delivered: bool,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    event_type = "delivered" if delivered else "delivery_failed"
    campaign_tags = await _get_campaign_tags(db, campaign_id)

    await db["email_events"].insert_one(
        {
            "event_type": event_type,
            "campaign_id": campaign_id,
            "recipient_email": recipient_email,
            "owner_user_id": owner_user_id,
            "campaign_tags": campaign_tags,
            "delivery_status": "delivered" if delivered else "failed",
            "error_message": error_message,
            "is_unique": True,
            "ts": now,
        }
    )

    update_doc = {
        "$setOnInsert": _recipient_stats_defaults(
            campaign_id, recipient_email, owner_user_id, now
        ),
        "$set": {
            "owner_user_id": owner_user_id,
            "campaign_tags": campaign_tags,
            "delivery_status": "delivered" if delivered else "failed",
            "updated_at": now,
        },
        "$max": {
            "last_delivered_at" if delivered else "last_delivery_failed_at": now,
        },
        "$inc": {
            "delivery_count" if delivered else "delivery_failure_count": 1,
        },
    }

    if delivered:
        update_doc["$min"] = {"first_delivered_at": now}
        update_doc["$unset"] = {"delivery_error": ""}
    else:
        update_doc["$min"] = {"first_delivery_failed_at": now}
        update_doc["$set"]["delivery_error"] = error_message or "Unknown delivery error"

    await db["campaign_recipient_stats"].update_one(
        {"campaign_id": campaign_id, "recipient_email": recipient_email},
        update_doc,
        upsert=True,
    )


async def record_engagement_event(
    *,
    db,
    event_type: str,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    ip: Optional[str],
    user_agent: Optional[str],
    link_url: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    campaign_tags = await _get_campaign_tags(db, campaign_id)

    if event_type == "open":
        unique_key = f"open:{campaign_id}:{recipient_email}"
    else:
        unique_key = f"click:{campaign_id}:{recipient_email}:{link_url or ''}"

    unique_exists = await db["tracking_uniques"].find_one({"_id": unique_key})
    is_unique = unique_exists is None
    if is_unique:
        await db["tracking_uniques"].insert_one({"_id": unique_key, "created_at": now})

    await db["email_events"].insert_one(
        {
            "event_type": event_type,
            "campaign_id": campaign_id,
            "recipient_email": recipient_email,
            "owner_user_id": owner_user_id,
            "campaign_tags": campaign_tags,
            "link_url": link_url,
            "ip": ip,
            "user_agent": user_agent,
            "is_unique": is_unique,
            "ts": now,
        }
    )

    stats_inc = {}
    stats_set = {
        "owner_user_id": owner_user_id,
        "campaign_tags": campaign_tags,
        "updated_at": now,
    }

    if event_type == "open":
        stats_inc["open_count"] = 1
        stats_set["last_open_at"] = now
        if is_unique:
            stats_inc["unique_open_count"] = 1

    if event_type == "click":
        stats_inc["click_count"] = 1
        stats_set["last_click_at"] = now
        if is_unique:
            stats_inc["unique_click_count"] = 1

    await db["campaign_recipient_stats"].update_one(
        {"campaign_id": campaign_id, "recipient_email": recipient_email},
        {
            "$setOnInsert": _recipient_stats_defaults(
                campaign_id, recipient_email, owner_user_id, now
            ),
            "$inc": stats_inc,
            "$set": stats_set,
        },
        upsert=True,
    )

    recipient = await db["recipients"].find_one(
        {"user_id": owner_user_id, "email": recipient_email}
    )

    if recipient:
        rec_inc = {}
        rec_set = {"updated_at": now}
        rec_add = {}

        if event_type == "open":
            rec_inc["engagement.open_count_total"] = 1
            rec_set["engagement.last_open_at"] = now
            if is_unique:
                rec_add["engagement.unique_open_campaigns"] = campaign_id
                for tag in campaign_tags:
                    rec_inc[f"engagement.tag_scores.{_tag_score_key(tag)}"] = 1

        if event_type == "click":
            rec_inc["engagement.click_count_total"] = 1
            rec_set["engagement.last_click_at"] = now
            if is_unique:
                rec_add["engagement.unique_click_campaigns"] = campaign_id

            if link_url:
                domain = urlparse(link_url).netloc.lower()
                if domain:
                    rec_add["engagement.clicked_domains"] = domain

        update_doc = {
            "$inc": rec_inc,
            "$set": rec_set,
        }
        if rec_add:
            update_doc["$addToSet"] = rec_add

        await db["recipients"].update_one({"_id": recipient["_id"]}, update_doc)
