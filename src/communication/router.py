from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from bson import ObjectId

from src.communication.schemas import CampaignCreate, CampaignResponse
from src.communication.models import CampaignDB
from src.communication.service import (
    normalize_campaign_channels,
    prepare_campaign_priority_dispatch,
)
from src.groups.service import resolve_static_group_emails
from src.auth.dependencies import get_current_active_user
from src.database import get_database

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


def ensure_aware_datetime(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return default or datetime.now(timezone.utc)


def normalize_campaign_tags(tags: List[str]) -> List[str]:
    normalized_tags = []
    seen = set()
    for tag in tags:
        clean_tag = str(tag).strip()
        if not clean_tag:
            continue
        key = clean_tag.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_tags.append(clean_tag)
    return normalized_tags


def dedupe_emails(emails: List[str]) -> List[str]:
    deduped_emails = []
    seen = set()
    for email in emails:
        clean_email = str(email).strip()
        if not clean_email:
            continue
        key = clean_email.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped_emails.append(clean_email)
    return deduped_emails


def get_campaign_channels(campaign: Dict[str, Any]) -> List[str]:
    channels = []
    for channel in campaign.get("channels", ["email"]) or ["email"]:
        normalized = str(channel).strip().lower()
        if normalized:
            channels.append(normalized)
    return channels or ["email"]


def supports_open_tracking(campaign: Dict[str, Any]) -> bool:
    return all(channel == "email" for channel in get_campaign_channels(campaign))

@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    campaign_in: CampaignCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
):
    db = get_database()
    
    try:
        # Verify template exists
        try:
            template = await db["templates"].find_one({"_id": ObjectId(campaign_in.template_id)})
        except Exception:
            template = await db["templates"].find_one({"_id": campaign_in.template_id})
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        campaign_payload = campaign_in.model_dump()
        campaign_payload["channels"] = normalize_campaign_channels(campaign_payload.get("channels", []))
        campaign_payload["tags"] = normalize_campaign_tags(campaign_payload.get("tags", []))
        group_emails = await resolve_static_group_emails(
            current_user["id"],
            campaign_payload.get("group_ids", []),
        )
        campaign_payload["recipients"] = dedupe_emails(
            [*campaign_payload.get("recipients", []), *group_emails]
        )
        campaign_payload["dynamic_groups"] = [
            request.model_dump(exclude_none=True)
            for request in campaign_in.dynamic_groups
        ]
        now = datetime.now(timezone.utc)
        has_audience = bool(campaign_payload["recipients"] or campaign_payload["dynamic_groups"])
        if has_audience:
            scheduled_at = campaign_payload.get("scheduled_at")
            if scheduled_at and scheduled_at > now:
                campaign_payload["status"] = "scheduled"
            else:
                campaign_payload["status"] = "queued"

        campaign_db = CampaignDB(
            **campaign_payload,
            created_by=current_user["id"]
        )
        
        campaign_dict = campaign_db.model_dump(by_alias=True, exclude_none=True)
        result = await db["campaigns"].insert_one(campaign_dict)
        campaign_id = str(result.inserted_id)
        campaign_dict["id"] = campaign_id

        if has_audience and campaign_payload["status"] == "queued":
            background_tasks.add_task(
                prepare_campaign_priority_dispatch,
                campaign_id,
                True,
            )
        
        return campaign_dict
    except Exception as e:
        print(f"ERROR creating campaign: {str(e)}")
        import traceback
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[CampaignResponse])
async def list_campaigns(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    cursor = db["campaigns"].find({"created_by": current_user["id"]})
    campaigns = await cursor.to_list(length=100)
    
    for camp in campaigns:
        camp.setdefault("channels", ["email"])
        camp.setdefault("tags", [])
        camp.setdefault("group_ids", [])
        camp["id"] = str(camp["_id"])
        
    return campaigns


@router.get("/stats", response_model=dict)
async def get_campaign_stats(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    pipeline = [
        {"$match": {"created_by": current_user["id"]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    results = await db["campaigns"].aggregate(pipeline).to_list(length=100)
    stats = {r["_id"]: r["count"] for r in results}
    stats["total"] = sum(stats.values())
    return stats


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: str, current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    try:
        query = {"_id": ObjectId(campaign_id)}
    except Exception:
        query = {"_id": campaign_id}
        
    campaign = await db["campaigns"].find_one(query)
    
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this campaign")

    campaign.setdefault("tags", [])
    campaign.setdefault("channels", ["email"])
    campaign.setdefault("group_ids", [])
    campaign["id"] = str(campaign["_id"])
    return campaign


@router.get("/{campaign_id}/analytics", response_model=Dict[str, Any])
async def get_campaign_analytics_endpoint(campaign_id: str, current_user: dict = Depends(get_current_active_user)):
    """Forward to the analytics service logic."""
    # To avoid circular imports or duplication, we can either move the logic to a service 
    # or just implement it here. Given the current structure, we'll implement it here 
    # to match the implementation in analytics/router.py
    db = get_database()
    
    # Verify campaign exists and belongs to user
    try:
        camp_query = {"_id": ObjectId(campaign_id)}
    except Exception:
        camp_query = {"_id": campaign_id}
        
    campaign = await db["campaigns"].find_one(camp_query)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # Aggregate Metrics
    pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": None,
            "total_opens": {"$sum": "$open_count"},
            "total_clicks": {"$sum": "$click_count"},
            "unique_opens": {"$sum": "$unique_open_count"},
            "unique_clicks": {"$sum": "$unique_click_count"}
        }}
    ]
    stats_result = await db["campaign_recipient_stats"].aggregate(pipeline).to_list(length=1)
    stats = stats_result[0] if stats_result else {
        "total_opens": 0, "total_clicks": 0, "unique_opens": 0, "unique_clicks": 0
    }

    delivered_count = await db["campaign_recipient_stats"].count_documents({
        "campaign_id": campaign_id,
        "delivery_status": "delivered"
    })
    failed_count = await db["campaign_recipient_stats"].count_documents({
        "campaign_id": campaign_id,
        "delivery_status": "failed"
    })
    
    channels = get_campaign_channels(campaign)
    open_tracking_enabled = supports_open_tracking(campaign)
    sent_count = len(campaign.get("recipients", [])) * max(len(channels), 1)
    open_tracking_sent_count = len(campaign.get("recipients", [])) if open_tracking_enabled else 0
    
    metrics = {
        "total_sent": sent_count,
        "delivered": delivered_count,
        "opened": stats["unique_opens"] if open_tracking_enabled else 0,
        "clicked": stats["unique_clicks"],
        "total_opens": stats["total_opens"] if open_tracking_enabled else 0,
        "total_clicks": stats["total_clicks"],
        "bounced": failed_count,
        "delivery_rate": round((delivered_count / sent_count * 100), 1) if sent_count > 0 else 0,
        "open_rate": round((stats["unique_opens"] / open_tracking_sent_count * 100), 1) if open_tracking_sent_count > 0 else 0,
        "click_rate": round((stats["unique_clicks"] / sent_count * 100), 1) if sent_count > 0 else 0,
        "bounce_rate": round((failed_count / sent_count * 100), 1) if sent_count > 0 else 0
    }
    
    # Accurate Timeline (Hours since creation)
    created_at = ensure_aware_datetime(campaign.get("created_at"))
    timeline_pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$project": {
            "hours_since": {"$floor": {"$divide": [{"$subtract": ["$ts", created_at]}, 3600000]}},
            "event_type": 1
        }},
        {"$match": {"hours_since": {"$gte": 0, "$lt": 72}}},
        {"$group": {
            "_id": "$hours_since",
            "opens": {"$sum": {"$cond": [{"$eq": ["$event_type", "open"]}, 1, 0]}},
            "clicks": {"$sum": {"$cond": [{"$eq": ["$event_type", "click"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}}
    ]
    timeline_results = await db["email_events"].aggregate(timeline_pipeline).to_list(length=72)
    
    # Recipient Activity
    recipients_cursor = db["campaign_recipient_stats"].find(
        {"campaign_id": campaign_id, "channel": "email"}
    ).limit(100)
    recipients_list = await recipients_cursor.to_list(length=100)
    
    recipient_emails = [r["recipient_email"] for r in recipients_list]
    recipients_cursor = db["recipients"].find(
        {"user_id": current_user["id"], "email": {"$in": recipient_emails}}
    )
    recipients_map = {}
    for recipient in await recipients_cursor.to_list(length=100):
        full_name = " ".join(
            part for part in [recipient.get("first_name"), recipient.get("last_name")] if part
        ).strip()
        recipients_map[recipient["email"]] = full_name or recipient["email"]

    users_cursor = db["users"].find({"email": {"$in": recipient_emails}})
    users_map = {u["email"]: u.get("full_name", u["email"]) for u in await users_cursor.to_list(length=100)}
    
    recipient_activity = []
    for r in recipients_list:
        email = r["recipient_email"]
        delivery_status = r.get("delivery_status", "pending")
        if r.get("click_count", 0) > 0:
            status_label = "Clicked"
        elif open_tracking_enabled and r.get("open_count", 0) > 0:
            status_label = "Opened"
        elif delivery_status == "failed":
            status_label = "Failed"
        else:
            status_label = "Delivered"
        recipient_activity.append({
            "email": email,
            "name": recipients_map.get(email) or users_map.get(email, email.split("@")[0]),
            "status": status_label,
            "delivery_status": delivery_status,
            "open_count": r.get("open_count", 0) if open_tracking_enabled else 0,
            "click_count": r.get("click_count", 0),
            "unique_open_count": r.get("unique_open_count", 0) if open_tracking_enabled else 0,
            "unique_click_count": r.get("unique_click_count", 0),
            "opened_at": r.get("last_open_at").isoformat() if open_tracking_enabled and r.get("last_open_at") else None,
            "clicked_at": r.get("last_click_at").isoformat() if r.get("last_click_at") else None,
        })
        
    return {
        "metrics": metrics,
        "supports_open_tracking": open_tracking_enabled,
        "timeline": [
            {
                "time": f"{int(r['_id'])}h",
                "opens": r["opens"] if open_tracking_enabled else 0,
                "clicks": r["clicks"],
            }
            for r in timeline_results
        ],
        "recipients": recipient_activity
    }
