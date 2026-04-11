import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from src.communication.messaging_service import MessagingService, html_to_text
from src.communication.tracking_service import ensure_recipient_stats, record_delivery_event
from src.communication.tracking_utils import inject_tracking
from src.config import settings
from src.database import get_database


ALLOWED_CAMPAIGN_CHANNELS = ("email", "sms", "whatsapp")


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


async def dispatch_campaign_by_id(campaign_id: str) -> None:
    db = get_database()
    if db is None:
        return

    campaign = await db["campaigns"].find_one(_campaign_query(campaign_id))
    if not campaign:
        return

    template = None
    try:
        template = await db["templates"].find_one({"_id": ObjectId(campaign["template_id"])})
    except Exception:
        template = await db["templates"].find_one({"_id": campaign["template_id"]})

    if not template:
        await db["campaigns"].update_one(
            _campaign_query(campaign_id),
            {"$set": {"status": "failed", "dispatch_error": "Template not found"}},
        )
        return

    recipients = campaign.get("recipients", [])
    channels = normalize_campaign_channels(campaign.get("channels", []))
    subject = campaign.get("subject") or template.get("subject", "No Subject")

    await db["campaigns"].update_one(
        _campaign_query(campaign_id),
        {
            "$set": {
                "status": "dispatching",
                "dispatch_started_at": datetime.now(timezone.utc),
                "dispatch_error": None,
            }
        },
    )

    recipient_data_map = {}
    if recipients:
        users_list = await db["users"].find({"email": {"$in": recipients}}).to_list(length=1000)
        recipient_data_map = {user["email"]: user for user in users_list}

    recipient_records = await _ensure_audience_recipients(
        db=db,
        owner_user_id=campaign["created_by"],
        recipients=recipients,
        recipient_data_map=recipient_data_map,
    )

    total_attempts = 0
    failed_attempts = 0

    for recipient_email in recipients:
        recipient_doc = recipient_records.get(recipient_email)
        user_data = recipient_data_map.get(recipient_email, {})
        rendered_html = render_campaign_content(
            template.get("body_html", ""),
            campaign.get("merge_data") or {},
            recipient_email,
            user_data,
        )
        rendered_text = html_to_text(rendered_html)

        for channel in channels:
            total_attempts += 1
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
                failed_attempts += 1

    if total_attempts == 0:
        new_status = "failed"
    elif failed_attempts == 0:
        new_status = "sent"
    elif failed_attempts < total_attempts:
        new_status = "partially_sent"
    else:
        new_status = "failed"

    await db["campaigns"].update_one(
        _campaign_query(campaign_id),
        {
            "$set": {
                "status": new_status,
                "dispatch_completed_at": datetime.now(timezone.utc),
                "delivery_summary": {
                    "total_attempts": total_attempts,
                    "failed_attempts": failed_attempts,
                    "successful_attempts": max(total_attempts - failed_attempts, 0),
                },
            }
        },
    )


async def dispatch_due_campaigns_once() -> int:
    db = get_database()
    if db is None:
        return 0

    dispatched = 0
    now = datetime.now(timezone.utc)

    while True:
        campaign = await db["campaigns"].find_one_and_update(
            {
                "status": "scheduled",
                "scheduled_at": {"$lte": now},
            },
            {
                "$set": {
                    "status": "dispatching",
                    "dispatch_started_at": now,
                }
            },
            sort=[("scheduled_at", 1)],
            return_document=ReturnDocument.AFTER,
        )

        if not campaign:
            break

        await dispatch_campaign_by_id(str(campaign["_id"]))
        dispatched += 1

    return dispatched


async def run_campaign_scheduler(stop_event: asyncio.Event) -> None:
    interval_seconds = max(settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS, 5)

    while not stop_event.is_set():
        try:
            await dispatch_due_campaigns_once()
        except Exception as exc:
            print(f"Campaign scheduler error: {exc}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
