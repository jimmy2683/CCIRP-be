from fastapi import APIRouter, Depends, HTTPException, Response
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import csv
import io
from src.auth.dependencies import get_current_active_user
from src.database import get_database

router = APIRouter(prefix="/analytics", tags=["Analytics"])

MIN_AWARE_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def ensure_aware_datetime(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return default or datetime.now(timezone.utc)


def get_campaign_channels(campaign: Dict[str, Any]) -> list[str]:
    channels = []
    for channel in campaign.get("channels", ["email"]) or ["email"]:
        normalized = str(channel).strip().lower()
        if normalized:
            channels.append(normalized)
    return channels or ["email"]


def supports_open_tracking(campaign: Dict[str, Any]) -> bool:
    return all(channel == "email" for channel in get_campaign_channels(campaign))

@router.get("/overview", response_model=Dict[str, Any])
async def get_analytics_overview(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    user_id = current_user["id"]
    
    # 1. Total Campaigns
    total_campaigns = await db["campaigns"].count_documents({"created_by": user_id})
    
    # 2. Global Metrics from campaign_recipient_stats
    user_campaigns_cursor = db["campaigns"].find(
        {"created_by": user_id},
        {"_id": 1, "recipients": 1, "channels": 1, "created_at": 1, "name": 1, "status": 1},
    )
    user_campaigns = await user_campaigns_cursor.to_list(length=1000)
    user_campaign_ids = [str(c["_id"]) for c in user_campaigns]
    
    pipeline = [
        {"$match": {"campaign_id": {"$in": user_campaign_ids}}},
        {"$group": {
            "_id": None,
            "total_opens": {"$sum": "$open_count"},
            "total_clicks": {"$sum": "$click_count"},
            "unique_opens": {"$sum": "$unique_open_count"},
            "unique_clicks": {"$sum": "$unique_click_count"},
        }}
    ]
    
    stats_result = await db["campaign_recipient_stats"].aggregate(pipeline).to_list(length=1)
    stats = stats_result[0] if stats_result else {
        "total_opens": 0, "total_clicks": 0, "unique_opens": 0, "unique_clicks": 0
    }

    failed_total = await db["campaign_recipient_stats"].count_documents({
        "owner_user_id": user_id,
        "delivery_status": "failed"
    })
    
    total_sent = sum(
        len(c.get("recipients", [])) * max(len(c.get("channels", ["email"])), 1)
        for c in user_campaigns
    )
    
    # 3. Trend Data (Last 30 Days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Sent counts from campaigns
    sent_by_date = {}
    for camp in user_campaigns:
        created_at = ensure_aware_datetime(camp.get("created_at"))
        if created_at >= thirty_days_ago:
            date_str = created_at.strftime("%Y-%m-%d")
            sent_by_date[date_str] = sent_by_date.get(date_str, 0) + (
                len(camp.get("recipients", [])) * max(len(camp.get("channels", ["email"])), 1)
            )
            
    # Events from email_events
    event_pipeline = [
        {"$match": {
            "owner_user_id": user_id,
            "ts": {"$gte": thirty_days_ago}
        }},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
            "delivered": {"$sum": {"$cond": [{"$eq": ["$event_type", "delivered"]}, 1, 0]}},
            "opened": {"$sum": {"$cond": [{"$eq": ["$event_type", "open"]}, 1, 0]}},
            "clicked": {"$sum": {"$cond": [{"$eq": ["$event_type", "click"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}}
    ]
    event_results = await db["email_events"].aggregate(event_pipeline).to_list(length=31)
    
    # Merge trend data
    all_dates = sorted(list(set(list(sent_by_date.keys()) + [r["_id"] for r in event_results])))
    trend_data = []
    for d in all_dates:
        ev = next(
            (r for r in event_results if r["_id"] == d),
            {"delivered": 0, "opened": 0, "clicked": 0},
        )
        sent = sent_by_date.get(d, 0)
        trend_data.append({
            "date": d,
            "sent": sent,
            "delivered": ev["delivered"],
            "opened": ev["opened"],
            "clicked": ev["clicked"]
        })
    
    # 4. Recent Campaign Performance
    recent_campaigns = sorted(
        user_campaigns,
        key=lambda x: ensure_aware_datetime(x.get("created_at"), MIN_AWARE_DATETIME),
        reverse=True,
    )[:5]
    
    performance = []
    for camp in recent_campaigns:
        camp_id = str(camp["_id"])
        c_stats_cursor = db["campaign_recipient_stats"].aggregate([
            {"$match": {"campaign_id": camp_id}},
            {"$group": {
                "_id": None,
                "opens": {"$sum": "$unique_open_count"},
                "clicks": {"$sum": "$unique_click_count"}
            }}
        ])
        c_stats_list = await c_stats_cursor.to_list(length=1)
        c_stats = c_stats_list[0] if c_stats_list else {"opens": 0, "clicks": 0}
        
        sent_count = len(camp.get("recipients", [])) * max(len(camp.get("channels", ["email"])), 1)
        open_rate = round((c_stats["opens"] / sent_count * 100), 1) if sent_count > 0 else 0
        click_rate = round((c_stats["clicks"] / sent_count * 100), 1) if sent_count > 0 else 0
        
        performance.append({
            "id": camp_id,
            "name": camp.get("name", "Unnamed"),
            "status": camp.get("status", "sent"),
            "sent": sent_count,
            "openRate": open_rate,
            "clickRate": click_rate,
            "date": ensure_aware_datetime(camp.get("created_at"), MIN_AWARE_DATETIME).strftime("%Y-%m-%d")
            if isinstance(camp.get("created_at"), datetime) else "N/A"
        })

    return {
        "total_campaigns": total_campaigns,
        "messages_sent": f"{total_sent}" if total_sent < 1000 else f"{total_sent/1000:.1f}K",
        "avg_open_rate": f"{round((stats['unique_opens'] / total_sent * 100), 1) if total_sent > 0 else 0}%",
        "avg_click_rate": f"{round((stats['unique_clicks'] / total_sent * 100), 1) if total_sent > 0 else 0}%",
        "bounce_rate": f"{round((failed_total / total_sent * 100), 1) if total_sent > 0 else 0}%",
        "unsubscribe_rate": "0.0%",
        "trend_data": trend_data,
        "campaign_performance": performance,
        "recent_campaigns": performance
    }

@router.get("/campaigns/{campaign_id}", response_model=Dict[str, Any])
async def get_campaign_analytics(campaign_id: str, current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    
    try:
        camp_query = {"_id": ObjectId(campaign_id)}
    except Exception:
        camp_query = {"_id": campaign_id}
        
    campaign = await db["campaigns"].find_one(camp_query)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
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
    
    recipients_cursor = db["campaign_recipient_stats"].find({"campaign_id": campaign_id, "channel": "email"}).limit(100)
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

@router.get("/campaigns/{campaign_id}/export")
async def export_campaign_analytics(campaign_id: str, current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    
    try:
        camp_query = {"_id": ObjectId(campaign_id)}
    except Exception:
        camp_query = {"_id": campaign_id}
        
    campaign = await db["campaigns"].find_one(camp_query)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    open_tracking_enabled = supports_open_tracking(campaign)

    # Export all up to 10k recipients
    recipients_cursor = db["campaign_recipient_stats"].find({"campaign_id": campaign_id, "channel": "email"})
    recipients_list = await recipients_cursor.to_list(length=10000)
    
    recipient_emails = [r["recipient_email"] for r in recipients_list]
    
    db_recipients_cursor = db["recipients"].find(
        {"user_id": current_user["id"], "email": {"$in": recipient_emails}}
    )
    recipients_map = {}
    for r in await db_recipients_cursor.to_list(length=10000):
        full_name = " ".join(
            part for part in [r.get("first_name"), r.get("last_name")] if part
        ).strip()
        recipients_map[r["email"]] = full_name or r["email"]

    users_cursor = db["users"].find({"email": {"$in": recipient_emails}})
    users_map = {u["email"]: u.get("full_name", u["email"]) for u in await users_cursor.to_list(length=10000)}

    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = ["Email", "Name", "Delivery Status"]
    if open_tracking_enabled:
        headers.append("Open Count")
        headers.append("Opened At")
    
    headers.extend(["Click Count", "Clicked At"])
    writer.writerow(headers)
    
    for r in recipients_list:
        email = r["recipient_email"]
        name = recipients_map.get(email) or users_map.get(email, email.split("@")[0])
        status = r.get("delivery_status", "pending")
        
        row = [email, name, status]
        if open_tracking_enabled:
            row.append(str(r.get("open_count", 0)))
            row.append(r.get("last_open_at").isoformat() if r.get("last_open_at") else "")
            
        row.append(str(r.get("click_count", 0)))
        row.append(r.get("last_click_at").isoformat() if r.get("last_click_at") else "")
        
        writer.writerow(row)

    csv_content = output.getvalue()
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}_analytics.csv"}
    )
