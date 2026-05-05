from datetime import datetime
from typing import Any

import google.generativeai as genai
from bson import ObjectId

from src.database import get_database


# ── serialization helpers ──────────────────────────────────────────────────

def _serialize(obj: Any) -> Any:
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj


def _dt(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ── Gemini tool definitions ────────────────────────────────────────────────

GEMINI_TOOLS = [
    genai.protos.Tool(function_declarations=[

        genai.protos.FunctionDeclaration(
            name="search_recipients",
            description="Search recipients by name, email, or tag. Returns matching contacts.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "query": genai.protos.Schema(type=genai.protos.Type.STRING, description="Search term to match against name, email, or tags"),
                    "limit": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Max results to return (default 20)"),
                },
                required=["query"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_recipient_detail",
            description="Get full engagement stats, tag scores, and consent flags for one recipient by email or ID.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "email_or_id": genai.protos.Schema(type=genai.protos.Type.STRING, description="Recipient email address or MongoDB ID"),
                },
                required=["email_or_id"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="list_campaigns",
            description="List campaigns sorted by newest first. Returns status, channels, tags, and delivery totals.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "limit": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Max campaigns to return (default 10)"),
                    "status_filter": genai.protos.Schema(type=genai.protos.Type.STRING, description="Filter by status: draft, queued, sending, sent, scheduled"),
                },
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_campaign_detail",
            description="Get full details, queue summary, and open/click analytics for one campaign.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "campaign_id": genai.protos.Schema(type=genai.protos.Type.STRING, description="MongoDB campaign ID"),
                },
                required=["campaign_id"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="list_templates",
            description="List available email, SMS, and WhatsApp templates.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "limit": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Max templates to return (default 20)"),
                },
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="list_static_groups",
            description="List all saved static audience groups with their recipient counts.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={},
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="list_dynamic_preferences",
            description="List saved dynamic group preferences (tag + top_k + min_interactions configs).",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={},
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="preview_dynamic_group",
            description="Preview the top-K recipients ranked by live engagement score for a given tag.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "tag": genai.protos.Schema(type=genai.protos.Type.STRING, description="Tag to score recipients on"),
                    "top_k": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Number of top recipients to return"),
                    "min_interactions": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Minimum interaction threshold (default 1)"),
                },
                required=["tag", "top_k"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="preview_ai_segmentation",
            description="Run AI-powered audience segmentation using semantic similarity between tags. Finds recipients from semantically related existing segments.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "tag": genai.protos.Schema(type=genai.protos.Type.STRING, description="Target tag for segmentation"),
                    "max_output_size": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Max recipients in result (default 20)"),
                    "similarity_threshold": genai.protos.Schema(type=genai.protos.Type.NUMBER, description="Min cosine similarity 0.0–1.0 (default 0.15)"),
                },
                required=["tag"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_analytics_overview",
            description="Get platform-wide analytics: total sent, open/click rates, top performing tags, and recent campaign summaries.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={},
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="create_static_group",
            description="Create and save a new static audience group from a list of recipient IDs.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "name": genai.protos.Schema(type=genai.protos.Type.STRING, description="Name for the new group"),
                    "recipient_ids": genai.protos.Schema(
                        type=genai.protos.Type.ARRAY,
                        items=genai.protos.Schema(type=genai.protos.Type.STRING),
                        description="List of recipient MongoDB IDs to include",
                    ),
                    "description": genai.protos.Schema(type=genai.protos.Type.STRING, description="Optional description"),
                },
                required=["name", "recipient_ids"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="save_dynamic_preference",
            description="Save a dynamic group preference (tag + default size) for reuse in campaigns.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "tag": genai.protos.Schema(type=genai.protos.Type.STRING, description="Tag for the dynamic group"),
                    "top_k": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Default group size (top-K recipients)"),
                    "min_interactions": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Minimum interaction threshold (default 1)"),
                },
                required=["tag", "top_k"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_engagement_heatmap",
            description=(
                "Analyse when the user's audience actually opens and clicks emails by aggregating all "
                "tracked open and click events across every campaign. Returns counts broken down by "
                "hour-of-day (0–23 UTC) and day-of-week, plus a ranked list of the top engagement "
                "windows. Use this to recommend the best send time for a campaign."
            ),
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "channel": genai.protos.Schema(type=genai.protos.Type.STRING, description="Filter by channel: 'email', 'sms', 'whatsapp'. Omit for all channels."),
                    "tag": genai.protos.Schema(type=genai.protos.Type.STRING, description="Filter to events from campaigns with this tag only."),
                    "event_type": genai.protos.Schema(type=genai.protos.Type.STRING, description="'open', 'click', or omit for both."),
                },
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_campaign_send_performance",
            description=(
                "Return per-campaign send timing and engagement metrics: when each campaign was sent, "
                "its open rate, click rate, and average time-to-first-open in hours. Use alongside "
                "get_engagement_heatmap to correlate send time choices with actual performance."
            ),
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "limit": genai.protos.Schema(type=genai.protos.Type.INTEGER, description="Max campaigns to return (default 20)."),
                    "channel": genai.protos.Schema(type=genai.protos.Type.STRING, description="Filter by channel: 'email', 'sms', 'whatsapp'. Omit for all."),
                },
                required=[],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="get_template_detail",
            description="Fetch the full content of a template by ID, including body_html. Call this before updating a template so you can see what is already there.",
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "template_id": genai.protos.Schema(type=genai.protos.Type.STRING, description="MongoDB template ID from list_templates"),
                },
                required=["template_id"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="create_template",
            description=(
                "Create a new message template and save it to the user's custom templates. "
                "Write complete, visually rich, production-ready content. "
                "For email: full HTML with inline CSS — use a clean layout, branded colours, clear hierarchy, "
                "and a compelling call-to-action. "
                "For SMS/WhatsApp: tight, friendly plain text with a clear action. "
                "Dynamic merge fields available: {{name}} (recipient full name), {{email}}, {{role}}, "
                "{{location}}, {{incident_type}}, {{timestamp}}. "
                "Weave merge fields naturally into subject lines, greetings, and body copy — "
                "personalisation dramatically improves open and click rates. "
                "The template is immediately accessible in the Templates section after creation."
            ),
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "name": genai.protos.Schema(type=genai.protos.Type.STRING, description="Template name, e.g. 'Monthly Newsletter'"),
                    "category": genai.protos.Schema(type=genai.protos.Type.STRING, description="Category, e.g. 'Marketing', 'Academic', 'Alert', 'Transactional'"),
                    "channel": genai.protos.Schema(type=genai.protos.Type.STRING, description="Delivery channel: 'email', 'sms', or 'whatsapp'"),
                    "subject": genai.protos.Schema(type=genai.protos.Type.STRING, description="Email subject line — make it specific and personal, e.g. 'Hi {{name}}, your update is here'"),
                    "body_html": genai.protos.Schema(type=genai.protos.Type.STRING, description="Full HTML body for email with inline styles, or plain text for SMS/WhatsApp."),
                },
                required=["name", "category", "channel", "body_html"],
            ),
        ),

        genai.protos.FunctionDeclaration(
            name="update_template",
            description=(
                "Update an existing custom template. Call get_template_detail first to read the current content, "
                "then supply only the fields you are changing. "
                "Apply the same quality bar as create_template: rich HTML, thorough use of merge fields, "
                "polished copy. The template version is incremented automatically."
            ),
            parameters=genai.protos.Schema(
                type=genai.protos.Type.OBJECT,
                properties={
                    "template_id": genai.protos.Schema(type=genai.protos.Type.STRING, description="MongoDB ID of the template to update"),
                    "name": genai.protos.Schema(type=genai.protos.Type.STRING, description="New template name (omit to keep existing)"),
                    "category": genai.protos.Schema(type=genai.protos.Type.STRING, description="New category (omit to keep existing)"),
                    "subject": genai.protos.Schema(type=genai.protos.Type.STRING, description="New email subject line (omit to keep existing)"),
                    "body_html": genai.protos.Schema(type=genai.protos.Type.STRING, description="Full updated HTML or plain text body (omit to keep existing)"),
                },
                required=["template_id"],
            ),
        ),

    ])
]


# ── tool implementations ───────────────────────────────────────────────────

async def _search_recipients(user_id: str, query: str, limit: int = 20) -> dict:
    db = get_database()
    limit = min(int(limit), 50)
    rx = {"$regex": str(query).strip(), "$options": "i"}
    docs = await db["recipients"].find(
        {"user_id": user_id, "$or": [{"email": rx}, {"first_name": rx}, {"last_name": rx}, {"tags": {"$elemMatch": rx}}]},
        {"_id": 1, "email": 1, "first_name": 1, "last_name": 1, "tags": 1, "status": 1, "engagement": 1},
    ).limit(limit).to_list(length=limit)

    out = []
    for r in docs:
        name = " ".join(filter(None, [r.get("first_name") or "", r.get("last_name") or ""])).strip() or r["email"]
        eng = r.get("engagement") or {}
        out.append({
            "id": str(r["_id"]),
            "email": r["email"],
            "name": name,
            "tags": r.get("tags") or [],
            "status": r.get("status", "active"),
            "last_open_at": _dt(eng.get("last_open_at")),
            "last_click_at": _dt(eng.get("last_click_at")),
        })
    return {"recipients": out, "count": len(out)}


async def _get_recipient_detail(user_id: str, email_or_id: str) -> dict:
    db = get_database()
    v = str(email_or_id).strip()
    q = {"user_id": user_id, "_id": ObjectId(v)} if ObjectId.is_valid(v) else {"user_id": user_id, "email": v.lower()}
    r = await db["recipients"].find_one(q)
    if not r:
        return {"error": "Recipient not found"}

    name = " ".join(filter(None, [r.get("first_name") or "", r.get("last_name") or ""])).strip() or r["email"]
    eng = r.get("engagement") or {}
    return {
        "id": str(r["_id"]),
        "email": r["email"],
        "name": name,
        "tags": r.get("tags") or [],
        "status": r.get("status", "active"),
        "consent_flags": r.get("consent_flags") or {},
        "engagement": {
            "open_count_total": eng.get("open_count_total", 0),
            "click_count_total": eng.get("click_count_total", 0),
            "last_open_at": _dt(eng.get("last_open_at")),
            "last_click_at": _dt(eng.get("last_click_at")),
            "tag_scores": eng.get("tag_scores") or {},
            "tag_interaction_counts": eng.get("tag_interaction_counts") or {},
        },
        "created_at": _dt(r.get("created_at")),
    }


async def _list_campaigns(user_id: str, limit: int = 10, status_filter: str = None) -> dict:
    db = get_database()
    limit = min(int(limit), 20)
    q = {"created_by": user_id}
    if status_filter:
        q["status"] = str(status_filter).strip()

    docs = await db["campaigns"].find(
        q,
        {"_id": 1, "name": 1, "status": 1, "channels": 1, "tags": 1, "created_at": 1, "queue_summary": 1, "delivery_summary": 1},
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    total = await db["campaigns"].count_documents({"created_by": user_id})

    return {
        "campaigns": [
            {
                "id": str(c["_id"]),
                "name": c["name"],
                "status": c.get("status", "draft"),
                "channels": c.get("channels") or [],
                "tags": c.get("tags") or [],
                "created_at": _dt(c.get("created_at")),
                "total_recipients": (c.get("queue_summary") or {}).get("total") or (c.get("delivery_summary") or {}).get("total_attempts") or 0,
                "delivered": (c.get("delivery_summary") or {}).get("successful_attempts") or 0,
            }
            for c in docs
        ],
        "shown": len(docs),
        "total": total,
    }


async def _get_campaign_detail(user_id: str, campaign_id: str) -> dict:
    db = get_database()
    if not ObjectId.is_valid(campaign_id):
        return {"error": "Invalid campaign ID"}
    c = await db["campaigns"].find_one({"_id": ObjectId(campaign_id), "created_by": user_id})
    if not c:
        return {"error": "Campaign not found"}

    agg = await db["campaign_recipient_stats"].aggregate([
        {"$match": {"campaign_id": campaign_id, "owner_user_id": user_id}},
        {"$group": {"_id": None, "total": {"$sum": 1}, "delivered": {"$sum": {"$ifNull": ["$delivery_count", 0]}}, "opens": {"$sum": {"$ifNull": ["$unique_open_count", 0]}}, "clicks": {"$sum": {"$ifNull": ["$unique_click_count", 0]}}}},
    ]).to_list(length=1)
    s = agg[0] if agg else {"total": 0, "delivered": 0, "opens": 0, "clicks": 0}
    total = s.get("total") or 0
    qs = c.get("queue_summary") or {}

    return {
        "id": str(c["_id"]),
        "name": c["name"],
        "subject": c.get("subject", ""),
        "status": c.get("status", "draft"),
        "channels": c.get("channels") or [],
        "tags": c.get("tags") or [],
        "created_at": _dt(c.get("created_at")),
        "scheduled_at": _dt(c.get("scheduled_at")),
        "queue": {"total": qs.get("total", 0), "completed": qs.get("completed", 0), "failed": qs.get("failed", 0)},
        "analytics": {
            "total_recipients": total,
            "delivered": s.get("delivered", 0),
            "unique_opens": s.get("opens", 0),
            "unique_clicks": s.get("clicks", 0),
            "open_rate": round(s.get("opens", 0) / total * 100, 1) if total else 0,
            "click_rate": round(s.get("clicks", 0) / total * 100, 1) if total else 0,
        },
    }


async def _list_templates(user_id: str, limit: int = 20) -> dict:
    db = get_database()
    limit = min(int(limit), 50)
    docs = await db["templates"].find(
        {"$or": [{"created_by": user_id}, {"is_common": True}]},
        {"_id": 1, "name": 1, "category": 1, "channel": 1, "subject": 1, "version": 1},
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return {
        "templates": [{"id": str(t["_id"]), "name": t["name"], "category": t.get("category", ""), "channel": t.get("channel", "email"), "subject": t.get("subject", ""), "version": t.get("version", 1)} for t in docs],
        "count": len(docs),
    }


async def _list_static_groups(user_id: str) -> dict:
    from src.groups.service import list_static_groups as _svc
    result = await _svc(user_id, skip=0, limit=50)
    return {
        "groups": [{"id": g["id"], "name": g["name"], "description": g.get("description"), "recipient_count": g.get("recipient_count", 0)} for g in result.get("items", [])],
        "total": result.get("total", 0),
    }


async def _list_dynamic_preferences(user_id: str) -> dict:
    from src.groups.service import list_dynamic_group_preferences as _svc
    prefs = await _svc(user_id)
    return {
        "preferences": [{"id": p["id"], "tag": p["tag"], "top_k": p["top_k"], "min_interactions": p["min_interactions"]} for p in prefs],
        "count": len(prefs),
    }


async def _preview_dynamic_group(user_id: str, tag: str, top_k: int, min_interactions: int = 1) -> dict:
    from src.groups.schemas import DynamicGroupResolveRequest
    from src.groups.service import resolve_dynamic_group_request as _svc
    result = await _svc(user_id, DynamicGroupResolveRequest(tag=tag, top_k=min(int(top_k), 100), min_interactions=int(min_interactions)))
    return {
        "tag": result["tag"],
        "top_k": result["top_k"],
        "total_eligible": result["total_eligible"],
        "recipients": [{"email": r["email"], "name": r["name"], "dynamic_score": r["dynamic_score"], "interaction_count": r["interaction_count"]} for r in result.get("recipients", [])[:20]],
    }


async def _preview_ai_segmentation(user_id: str, tag: str, max_output_size: int = 20, similarity_threshold: float = 0.15) -> dict:
    from src.groups.schemas import SegmentationRequest
    from src.groups.service import resolve_segmentation as _svc
    result = await _svc(user_id, SegmentationRequest(tag=tag, max_output_size=min(int(max_output_size), 50), similarity_threshold=float(similarity_threshold)))
    return {
        "tag": result["tag"],
        "recipient_count": result["recipient_count"],
        "total_matched_groups": result["total_matched_groups"],
        "top_recipients": [{"email": r["email"], "name": r["name"], "dynamic_score": r["dynamic_score"]} for r in result.get("recipients", [])[:15]],
        "group_contributions": [{"tag": gc["tag"], "similarity_score": gc["similarity_score"], "selected_count": gc["selected_count"]} for gc in result.get("group_contributions", [])[:5]],
    }


async def _get_analytics_overview(user_id: str) -> dict:
    db = get_database()
    total_campaigns = await db["campaigns"].count_documents({"created_by": user_id})

    agg = await db["campaign_recipient_stats"].aggregate([
        {"$match": {"owner_user_id": user_id}},
        {"$group": {"_id": None, "total_sent": {"$sum": {"$ifNull": ["$delivery_count", 0]}}, "total_opens": {"$sum": {"$ifNull": ["$unique_open_count", 0]}}, "total_clicks": {"$sum": {"$ifNull": ["$unique_click_count", 0]}}}},
    ]).to_list(length=1)
    ov = agg[0] if agg else {"total_sent": 0, "total_opens": 0, "total_clicks": 0}
    total_sent = ov.get("total_sent", 0)

    top_tags = await db["campaign_recipient_stats"].aggregate([
        {"$match": {"owner_user_id": user_id, "campaign_tag_keys": {"$exists": True, "$ne": []}}},
        {"$unwind": "$campaign_tag_keys"},
        {"$group": {"_id": "$campaign_tag_keys", "opens": {"$sum": {"$ifNull": ["$unique_open_count", 0]}}, "clicks": {"$sum": {"$ifNull": ["$unique_click_count", 0]}}}},
        {"$sort": {"opens": -1}},
        {"$limit": 5},
    ]).to_list(length=5)

    recent = await db["campaigns"].find({"created_by": user_id}, {"_id": 1, "name": 1, "status": 1, "created_at": 1}).sort("created_at", -1).limit(5).to_list(length=5)

    return {
        "total_campaigns": total_campaigns,
        "total_sent": total_sent,
        "total_unique_opens": ov.get("total_opens", 0),
        "total_unique_clicks": ov.get("total_clicks", 0),
        "open_rate": round(ov.get("total_opens", 0) / total_sent * 100, 1) if total_sent else 0,
        "click_rate": round(ov.get("total_clicks", 0) / total_sent * 100, 1) if total_sent else 0,
        "top_tags": [{"tag": t["_id"], "opens": t["opens"], "clicks": t["clicks"]} for t in top_tags],
        "recent_campaigns": [{"id": str(c["_id"]), "name": c["name"], "status": c.get("status", "draft"), "created_at": _dt(c.get("created_at"))} for c in recent],
    }


async def _create_static_group(user_id: str, name: str, recipient_ids: list, description: str = None) -> dict:
    from src.groups.schemas import StaticGroupCreate
    from src.groups.service import create_static_group as _svc
    result = await _svc(user_id, StaticGroupCreate(name=name, description=description, recipient_ids=list(recipient_ids), import_group_ids=[]))
    return {"id": result["id"], "name": result["name"], "recipient_count": result["recipient_count"], "message": f"Group '{name}' created with {result['recipient_count']} recipients."}


_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]  # $dayOfWeek: 1=Sun


async def _get_engagement_heatmap(
    user_id: str,
    channel: str = None,
    tag: str = None,
    event_type: str = None,
) -> dict:
    db = get_database()

    match: dict = {"owner_user_id": user_id, "is_unique": True}
    if event_type and event_type in ("open", "click"):
        match["event_type"] = event_type
    else:
        match["event_type"] = {"$in": ["open", "click"]}
    if channel:
        match["channel"] = str(channel).lower().strip()
    if tag:
        match["campaign_tag_keys"] = {"$elemMatch": {"$regex": str(tag).strip(), "$options": "i"}}

    # Aggregate by day-of-week (1=Sun…7=Sat) and hour (0–23), both in UTC
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "dow": {"$dayOfWeek": "$ts"},
                "hour": {"$hour": "$ts"},
                "event_type": "$event_type",
            },
            "count": {"$sum": 1},
        }},
    ]
    rows = await db["email_events"].aggregate(pipeline).to_list(length=None)

    # Reshape into hour_summary and day_summary
    hour_totals: dict[int, dict] = {h: {"hour": h, "opens": 0, "clicks": 0} for h in range(24)}
    day_totals: dict[int, dict] = {d: {"day": _DAY_NAMES[d - 1], "opens": 0, "clicks": 0} for d in range(1, 8)}

    for row in rows:
        dow = row["_id"]["dow"]
        hour = row["_id"]["hour"]
        et = row["_id"]["event_type"]
        count = row["count"]
        key = "opens" if et == "open" else "clicks"
        hour_totals[hour][key] += count
        day_totals[dow][key] += count

    hour_list = sorted(hour_totals.values(), key=lambda x: x["opens"] + x["clicks"], reverse=True)
    day_list = sorted(day_totals.values(), key=lambda x: x["opens"] + x["clicks"], reverse=True)

    total_opens = sum(h["opens"] for h in hour_list)
    total_clicks = sum(h["clicks"] for h in hour_list)

    # Top 5 windows (hour + day combinations)
    combo_totals: dict[tuple, dict] = {}
    for row in rows:
        dow = row["_id"]["dow"]
        hour = row["_id"]["hour"]
        et = row["_id"]["event_type"]
        key = (dow, hour)
        if key not in combo_totals:
            combo_totals[key] = {"day": _DAY_NAMES[dow - 1], "hour": hour, "opens": 0, "clicks": 0}
        combo_totals[key]["opens" if et == "open" else "clicks"] += row["count"]

    top_windows = sorted(combo_totals.values(), key=lambda x: x["opens"] + x["clicks"], reverse=True)[:5]

    return {
        "total_unique_opens": total_opens,
        "total_unique_clicks": total_clicks,
        "note": "All times are UTC. Recommend converting to your audience's local timezone.",
        "top_windows": top_windows,
        "by_hour": hour_list,
        "by_day": day_list,
    }


async def _get_campaign_send_performance(
    user_id: str,
    limit: int = 20,
    channel: str = None,
) -> dict:
    db = get_database()
    limit = min(int(limit), 50)

    match: dict = {"owner_user_id": user_id}
    if channel:
        match["channel"] = str(channel).lower().strip()

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$campaign_id",
            "total_recipients": {"$sum": 1},
            "delivered": {"$sum": {"$ifNull": ["$delivery_count", 0]}},
            "unique_opens": {"$sum": {"$ifNull": ["$unique_open_count", 0]}},
            "unique_clicks": {"$sum": {"$ifNull": ["$unique_click_count", 0]}},
            "first_delivered_at": {"$min": "$first_delivered_at"},
            "avg_open_lag_ms": {
                "$avg": {
                    "$cond": [
                        {"$and": [
                            {"$gt": ["$last_open_at", None]},
                            {"$gt": ["$first_delivered_at", None]},
                        ]},
                        {"$subtract": ["$last_open_at", "$first_delivered_at"]},
                        None,
                    ]
                }
            },
        }},
        {"$sort": {"first_delivered_at": -1}},
        {"$limit": limit},
    ]
    stats = await db["campaign_recipient_stats"].aggregate(pipeline).to_list(length=limit)

    # Fetch campaign names in one query
    campaign_ids = [r["_id"] for r in stats if r["_id"] and ObjectId.is_valid(r["_id"])]
    campaigns_map = {}
    if campaign_ids:
        camp_docs = await db["campaigns"].find(
            {"_id": {"$in": [ObjectId(cid) for cid in campaign_ids]}},
            {"_id": 1, "name": 1, "scheduled_at": 1, "created_at": 1, "channels": 1},
        ).to_list(length=limit)
        campaigns_map = {str(c["_id"]): c for c in camp_docs}

    out = []
    for r in stats:
        cid = r["_id"]
        camp = campaigns_map.get(cid, {})
        delivered = r.get("delivered") or 0
        opens = r.get("unique_opens") or 0
        clicks = r.get("unique_clicks") or 0
        sent_at = camp.get("scheduled_at") or r.get("first_delivered_at") or camp.get("created_at")
        avg_lag_h = round(r["avg_open_lag_ms"] / 3_600_000, 1) if r.get("avg_open_lag_ms") else None
        out.append({
            "campaign_id": cid,
            "name": camp.get("name", cid),
            "channels": camp.get("channels") or [],
            "sent_at": _dt(sent_at),
            "delivered": delivered,
            "unique_opens": opens,
            "unique_clicks": clicks,
            "open_rate_pct": round(opens / delivered * 100, 1) if delivered else 0,
            "click_rate_pct": round(clicks / delivered * 100, 1) if delivered else 0,
            "avg_time_to_open_hours": avg_lag_h,
        })

    return {"campaigns": out, "count": len(out)}


async def _get_template_detail(user_id: str, template_id: str) -> dict:
    db = get_database()
    if not ObjectId.is_valid(template_id):
        return {"error": "Invalid template ID"}
    t = await db["templates"].find_one(
        {"_id": ObjectId(template_id), "$or": [{"created_by": user_id}, {"is_common": True}]}
    )
    if not t:
        return {"error": "Template not found"}
    return {
        "id": str(t["_id"]),
        "name": t["name"],
        "category": t.get("category", ""),
        "channel": t.get("channel", "email"),
        "subject": t.get("subject"),
        "body_html": t.get("body_html", ""),
        "is_common": t.get("is_common", False),
        "version": t.get("version", 1),
        "created_by": t.get("created_by"),
    }


async def _update_template(
    user_id: str,
    template_id: str,
    name: str = None,
    category: str = None,
    subject: str = None,
    body_html: str = None,
) -> dict:
    db = get_database()
    if not ObjectId.is_valid(template_id):
        return {"error": "Invalid template ID"}

    t = await db["templates"].find_one({"_id": ObjectId(template_id), "created_by": user_id})
    if not t:
        return {"error": "Template not found or you do not own it"}

    update: dict = {"updated_at": datetime.utcnow()}
    if name is not None:
        update["name"] = str(name).strip()
    if category is not None:
        update["category"] = str(category).strip()
    if subject is not None:
        update["subject"] = str(subject).strip()
    if body_html is not None:
        update["body_html"] = body_html

    if len(update) == 1:  # only updated_at — nothing to change
        return {"error": "No fields provided to update"}

    # Archive current version to template_history before overwriting
    await db["template_history"].insert_one({
        "template_id": ObjectId(template_id),
        "version": t.get("version", 1),
        "name": t["name"],
        "subject": t.get("subject"),
        "body_html": t.get("body_html", ""),
        "design_json": t.get("design_json"),
        "updated_at": t.get("updated_at", datetime.utcnow()),
        "saved_at": datetime.utcnow(),
    })

    await db["templates"].update_one(
        {"_id": ObjectId(template_id)},
        {"$set": update, "$inc": {"version": 1}},
    )

    new_version = t.get("version", 1) + 1
    return {
        "id": template_id,
        "name": update.get("name", t["name"]),
        "version": new_version,
        "message": f"Template updated to version {new_version}.",
    }


async def _create_template(
    user_id: str,
    name: str,
    category: str,
    channel: str,
    body_html: str,
    subject: str = None,
) -> dict:
    db = get_database()
    channel = str(channel).lower().strip()
    doc = {
        "name": str(name).strip(),
        "category": str(category).strip(),
        "channel": channel,
        "subject": str(subject).strip() if subject else None,
        "body_html": body_html,
        "design_json": None,
        "is_common": False,
        "created_by": user_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "version": 1,
    }
    result = await db["templates"].insert_one(doc)
    template_id = str(result.inserted_id)
    return {
        "id": template_id,
        "name": doc["name"],
        "category": doc["category"],
        "channel": doc["channel"],
        "subject": doc["subject"],
        "version": 1,
        "message": f"Template '{doc['name']}' created and saved to your custom templates.",
    }


async def _save_dynamic_preference(user_id: str, tag: str, top_k: int, min_interactions: int = 1) -> dict:
    from src.groups.schemas import DynamicGroupPreferenceUpsert, SegmentationRequest, StaticGroupCreate
    from src.groups.service import upsert_dynamic_group_preference as _svc
    from src.groups.service import resolve_segmentation, create_static_group

    # 1. Save dynamic preference
    result = await _svc(user_id, DynamicGroupPreferenceUpsert(tag=tag, top_k=int(top_k), min_interactions=int(min_interactions)))

    # 2. Perform Smart Segmentation to get the current snapshot of top_k users
    try:
        segmentation_response = await resolve_segmentation(
            user_id,
            SegmentationRequest(tag=tag, max_output_size=int(top_k), similarity_threshold=0.15)
        )

        recipient_ids = segmentation_response.get("recipient_ids", [])
        static_group_msg = "No recipients found for smart segment."
        static_group_id = None

        # 3. Save as a static group
        if recipient_ids:
            group_name = f"Smart Segment: {tag} (Top {top_k})"
            static_group = await create_static_group(
                user_id,
                StaticGroupCreate(
                    name=group_name,
                    description=f"AI segmented static group for '{tag}'",
                    recipient_ids=recipient_ids,
                    import_group_ids=[]
                )
            )
            static_group_id = static_group["id"]
            static_group_msg = f"Created static group '{group_name}' with {len(recipient_ids)} recipients."

        return {
            "id": result["id"],
            "static_group_id": static_group_id,
            "tag": result["tag"],
            "top_k": result["top_k"],
            "min_interactions": result["min_interactions"],
            "message": f"Dynamic preference saved for '{tag}' (top_k={top_k}). {static_group_msg}"
        }
    except Exception as exc:
        return {
            "id": result["id"],
            "tag": result["tag"],
            "top_k": result["top_k"],
            "min_interactions": result["min_interactions"],
            "message": f"Dynamic preference saved for '{tag}' (top_k={top_k}), but smart segmentation failed: {exc}"
        }


# ── dispatcher ─────────────────────────────────────────────────────────────

_REGISTRY = {
    "search_recipients": _search_recipients,
    "get_recipient_detail": _get_recipient_detail,
    "list_campaigns": _list_campaigns,
    "get_campaign_detail": _get_campaign_detail,
    "list_templates": _list_templates,
    "list_static_groups": _list_static_groups,
    "list_dynamic_preferences": _list_dynamic_preferences,
    "preview_dynamic_group": _preview_dynamic_group,
    "preview_ai_segmentation": _preview_ai_segmentation,
    "get_analytics_overview": _get_analytics_overview,
    "create_static_group": _create_static_group,
    "save_dynamic_preference": _save_dynamic_preference,
    "get_engagement_heatmap": _get_engagement_heatmap,
    "get_campaign_send_performance": _get_campaign_send_performance,
    "get_template_detail": _get_template_detail,
    "create_template": _create_template,
    "update_template": _update_template,
}


async def execute_tool(user_id: str, name: str, args: dict) -> dict:
    fn = _REGISTRY.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await fn(user_id=user_id, **args)
    except Exception as exc:
        return {"error": str(exc)}
