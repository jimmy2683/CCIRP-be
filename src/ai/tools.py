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


async def _save_dynamic_preference(user_id: str, tag: str, top_k: int, min_interactions: int = 1) -> dict:
    from src.groups.schemas import DynamicGroupPreferenceUpsert
    from src.groups.service import upsert_dynamic_group_preference as _svc
    result = await _svc(user_id, DynamicGroupPreferenceUpsert(tag=tag, top_k=int(top_k), min_interactions=int(min_interactions)))
    return {"id": result["id"], "tag": result["tag"], "top_k": result["top_k"], "min_interactions": result["min_interactions"], "message": f"Dynamic preference saved for '{tag}' (top_k={top_k})."}


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
}


async def execute_tool(user_id: str, name: str, args: dict) -> dict:
    fn = _REGISTRY.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await fn(user_id=user_id, **args)
    except Exception as exc:
        return {"error": str(exc)}
