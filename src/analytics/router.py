from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from bson import ObjectId

from src.auth.dependencies import get_current_active_user
from src.database import get_database

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/overview", response_model=Dict[str, Any])
async def get_analytics_overview(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    user_id = current_user["id"]
    
    # 1. Total Campaigns
    total_campaigns = await db["campaigns"].count_documents({"created_by": user_id})
    
    # 2. Global Metrics from campaign_recipient_stats
    user_campaigns_cursor = db["campaigns"].find({"created_by": user_id}, {"_id": 1, "recipients": 1, "created_at": 1})
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
    
    total_sent = sum(len(c.get("recipients", [])) for c in user_campaigns)
    
    # 3. Trend Data (Last 30 Days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Sent counts from campaigns
    sent_by_date = {}
    for camp in user_campaigns:
        if "created_at" in camp and camp["created_at"] >= thirty_days_ago:
            date_str = camp["created_at"].strftime("%Y-%m-%d")
            sent_by_date[date_str] = sent_by_date.get(date_str, 0) + len(camp.get("recipients", []))
            
    # Events from email_events
    event_pipeline = [
        {"$match": {
            "owner_user_id": user_id,
            "ts": {"$gte": thirty_days_ago}
        }},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
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
        ev = next((r for r in event_results if r["_id"] == d), {"opened": 0, "clicked": 0})
        sent = sent_by_date.get(d, 0)
        trend_data.append({
            "date": d,
            "sent": sent,
            "delivered": sent, # Assume delivered = sent
            "opened": ev["opened"],
            "clicked": ev["clicked"]
        })
    
    # 4. Recent Campaign Performance
    recent_campaigns = sorted(user_campaigns, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:5]
    
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
        
        sent_count = len(camp.get("recipients", []))
        open_rate = round((c_stats["opens"] / sent_count * 100), 1) if sent_count > 0 else 0
        click_rate = round((c_stats["clicks"] / sent_count * 100), 1) if sent_count > 0 else 0
        
        performance.append({
            "id": camp_id,
            "name": camp.get("name", "Unnamed"),
            "status": camp.get("status", "sent"),
            "sent": sent_count,
            "openRate": open_rate,
            "clickRate": click_rate,
            "date": camp["created_at"].strftime("%Y-%m-%d") if isinstance(camp.get("created_at"), datetime) else "N/A"
        })

    return {
        "total_campaigns": total_campaigns,
        "messages_sent": f"{total_sent}" if total_sent < 1000 else f"{total_sent/1000:.1f}K",
        "avg_open_rate": f"{round((stats['unique_opens'] / total_sent * 100), 1) if total_sent > 0 else 0}%",
        "avg_click_rate": f"{round((stats['unique_clicks'] / total_sent * 100), 1) if total_sent > 0 else 0}%",
        "bounce_rate": "0.0%",
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
    except:
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
    
    sent_count = len(campaign.get("recipients", []))
    
    metrics = {
        "total_sent": sent_count,
        "delivered": sent_count,
        "opened": stats["unique_opens"],
        "clicked": stats["unique_clicks"],
        "bounced": 0,
        "delivery_rate": 100.0 if sent_count > 0 else 0,
        "open_rate": round((stats["unique_opens"] / sent_count * 100), 1) if sent_count > 0 else 0,
        "click_rate": round((stats["unique_clicks"] / sent_count * 100), 1) if sent_count > 0 else 0,
        "bounce_rate": 0.0
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
    
    recipients_cursor = db["campaign_recipient_stats"].find({"campaign_id": campaign_id}).limit(100)
    recipients_list = await recipients_cursor.to_list(length=100)
    
    recipient_emails = [r["recipient_email"] for r in recipients_list]
    users_cursor = db["users"].find({"email": {"$in": recipient_emails}})
    users_map = {u["email"]: u.get("full_name", u["email"]) for u in await users_cursor.to_list(length=100)}
    
    recipient_activity = []
    for r in recipients_list:
        email = r["recipient_email"]
        recipient_activity.append({
            "email": email,
            "name": users_map.get(email, email.split("@")[0]),
            "status": "Clicked" if r.get("click_count", 0) > 0 else ("Opened" if r.get("open_count", 0) > 0 else "Delivered"),
            "opened_at": r.get("last_open_at").isoformat() if r.get("last_open_at") else None,
            "clicked_at": r.get("last_click_at").isoformat() if r.get("last_click_at") else None,
        })
        
    return {
        "metrics": metrics,
        "timeline": [{"time": f"{int(r['_id'])}h", "opens": r["opens"], "clicks": r["clicks"]} for r in timeline_results],
        "recipients": recipient_activity
    }
