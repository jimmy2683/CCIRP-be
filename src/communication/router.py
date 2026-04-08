import re
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from bson import ObjectId

from src.config import settings
from src.communication.tracking_service import ensure_recipient_stats, record_delivery_event
from src.communication.tracking_utils import inject_tracking
from src.communication.schemas import CampaignCreate, CampaignResponse
from src.communication.models import CampaignDB
from src.communication.email_service import EmailService
from src.auth.dependencies import get_current_active_user
from src.database import get_database

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


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


def render_template(body_html: str, merge_data: dict, recipient_email: str, recipient_data: dict) -> str:
    """Replace all {{field}} merge fields in the template body."""
    rendered = body_html
    
    # Start with campaign-level merge data (organization_name, event_name, etc.)
    all_fields = dict(merge_data)
    
    # Add/override with recipient-specific fields
    all_fields["email"] = recipient_email
    all_fields["recipient_email"] = recipient_email
    full_name = recipient_data.get("full_name", recipient_email.split("@")[0])
    all_fields["name"] = full_name
    all_fields["full_name"] = full_name
    all_fields["recipient_name"] = full_name
    all_fields["first_name"] = full_name.split(" ")[0] if full_name else ""
    
    # Replace all {{field}} patterns
    for key, value in all_fields.items():
        rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", str(value), rendered, flags=re.IGNORECASE)
    
    return rendered


async def dispatch_campaign_emails(campaign_id: str, owner_user_id: str, template: dict, recipients: List[str], subject: str, merge_data: dict):
    """Background task to send emails to all recipients and update campaign status."""
    db = get_database()
    body_html = template.get("body_html", "")
    
    # Look up recipient user data for merge fields
    recipient_data_map = {}
    if recipients:
        users_cursor = db["users"].find({"email": {"$in": recipients}})
        users_list = await users_cursor.to_list(length=1000)
        for u in users_list:
            recipient_data_map[u["email"]] = u

    failed = []
    for email in recipients:
        await ensure_recipient_stats(
            db=db,
            campaign_id=campaign_id,
            recipient_email=email,
            owner_user_id=owner_user_id,
        )
        user_data = recipient_data_map.get(email, {})
        rendered_body = render_template(body_html, merge_data, email, user_data)
        tracked_body = inject_tracking(rendered_body, campaign_id, email, owner_user_id, settings.TRACKING_BASE_URL)
        success, msg = await EmailService.send_email([email], subject, tracked_body)
        await record_delivery_event(
            db=db,
            campaign_id=campaign_id,
            recipient_email=email,
            owner_user_id=owner_user_id,
            delivered=success,
            error_message=None if success else msg,
        )
        if not success:
            print(f"Failed to send to {email}: {msg}")
            failed.append(email)
    
    # Update campaign status
    new_status = "sent" if not failed else ("partially_sent" if len(failed) < len(recipients) else "failed")
    try:
        await db["campaigns"].update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": {"status": new_status}}
        )
    except Exception:
        await db["campaigns"].update_one(
            {"_id": campaign_id},
            {"$set": {"status": new_status}}
        )
    print(f"Campaign {campaign_id} dispatch complete. Status: {new_status}. Failed: {len(failed)}/{len(recipients)}")


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
        campaign_payload["tags"] = normalize_campaign_tags(campaign_payload.get("tags", []))

        campaign_db = CampaignDB(
            **campaign_payload,
            created_by=current_user["id"]
        )
        
        campaign_dict = campaign_db.model_dump(by_alias=True, exclude_none=True)
        result = await db["campaigns"].insert_one(campaign_dict)
        campaign_id = str(result.inserted_id)
        campaign_dict["id"] = campaign_id

        # Dispatch emails in background
        subject = campaign_in.subject or template.get("subject", "No Subject")
        if campaign_in.recipients:
            background_tasks.add_task(
                dispatch_campaign_emails,
                campaign_id,
                current_user["id"],
                template,
                campaign_in.recipients,
                subject,
                campaign_in.merge_data or {},
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
        camp.setdefault("tags", [])
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
    except:
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
    
    sent_count = len(campaign.get("recipients", []))
    
    metrics = {
        "total_sent": sent_count,
        "delivered": delivered_count,
        "opened": stats["unique_opens"],
        "clicked": stats["unique_clicks"],
        "bounced": failed_count,
        "delivery_rate": round((delivered_count / sent_count * 100), 1) if sent_count > 0 else 0,
        "open_rate": round((stats["unique_opens"] / sent_count * 100), 1) if sent_count > 0 else 0,
        "click_rate": round((stats["unique_clicks"] / sent_count * 100), 1) if sent_count > 0 else 0,
        "bounce_rate": round((failed_count / sent_count * 100), 1) if sent_count > 0 else 0
    }
    
    # Accurate Timeline (Hours since creation)
    created_at = campaign.get("created_at", datetime.now(timezone.utc))
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
    recipients_cursor = db["campaign_recipient_stats"].find({"campaign_id": campaign_id}).limit(100)
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
        elif r.get("open_count", 0) > 0:
            status_label = "Opened"
        elif delivery_status == "failed":
            status_label = "Failed"
        else:
            status_label = "Delivered"
        recipient_activity.append({
            "email": email,
            "name": recipients_map.get(email) or users_map.get(email, email.split("@")[0]),
            "status": status_label,
            "opened_at": r.get("last_open_at").isoformat() if r.get("last_open_at") else None,
            "clicked_at": r.get("last_click_at").isoformat() if r.get("last_click_at") else None,
        })
        
    return {
        "metrics": metrics,
        "timeline": [{"time": f"{int(r['_id'])}h", "opens": r["opens"], "clicks": r["clicks"]} for r in timeline_results],
        "recipients": recipient_activity
    }
