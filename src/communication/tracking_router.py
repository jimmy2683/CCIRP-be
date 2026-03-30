from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from src.database import get_database
from src.communication.tracking_utils import TRANSPARENT_PNG_BYTES, verify_tracking_token


router = APIRouter(prefix="/track", tags=["Tracking"])
db = get_database()

# TODO: Update when dynamic groups are implemented to use actual group metadata instead of heuristics based on URL keywords
def _topic_from_url(url: str) -> Optional[str]:
    text = (url or "").lower()
    if any(k in text for k in ["tech", "dev", "github", "ai", "python", "cloud"]):
        return "tech"
    if any(k in text for k in ["finance", "invest", "stocks", "money"]):
        return "finance"
    if any(k in text for k in ["health", "fitness", "wellness"]):
        return "health"
    return None


async def _record_event(
    *,
    event_type: str,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    ip: Optional[str],
    user_agent: Optional[str],
    link_url: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)

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
            "link_url": link_url,
            "ip": ip,
            "user_agent": user_agent,
            "is_unique": is_unique,
            "ts": now,
        }
    )

    stats_inc = {}
    stats_set = {}

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
            "$setOnInsert": {
                "campaign_id": campaign_id,
                "recipient_email": recipient_email,
            },
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

        if event_type == "click":
            rec_inc["engagement.click_count_total"] = 1
            rec_set["engagement.last_click_at"] = now
            if is_unique:
                rec_add["engagement.unique_click_campaigns"] = campaign_id

            if link_url:
                domain = urlparse(link_url).netloc.lower()
                if domain:
                    rec_add["engagement.clicked_domains"] = domain

                topic = _topic_from_url(link_url)
                if topic:
                    rec_inc[f"engagement.topic_scores.{topic}"] = 1

        update_doc = {
            "$inc": rec_inc,
            "$set": rec_set,
        }
        if rec_add:
            update_doc["$addToSet"] = rec_add

        await db["recipients"].update_one({"_id": recipient["_id"]}, update_doc)


@router.get("/open/{token}.png")
async def track_open(token: str, request: Request):
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        return Response(content=TRANSPARENT_PNG_BYTES, media_type="image/png")

    await _record_event(
        event_type="open",
        campaign_id=str(payload["c"]),
        recipient_email=str(payload["r"]),
        owner_user_id=str(payload["o"]),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return Response(content=TRANSPARENT_PNG_BYTES, media_type="image/png")


@router.get("/click/{token}")
async def track_click(token: str, request: Request, u: str = Query(..., description="Destination URL")):
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    await _record_event(
        event_type="click",
        campaign_id=str(payload["c"]),
        recipient_email=str(payload["r"]),
        owner_user_id=str(payload["o"]),
        link_url=u,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return RedirectResponse(url=u, status_code=302)