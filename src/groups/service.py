import csv
import io
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from bson import ObjectId
from fastapi import HTTPException
from fastapi import UploadFile

from src.database import get_database
from src.groups.models import DynamicGroupPreferenceDB, GroupDB
from src.groups.schemas import (
    DynamicGroupPreferenceUpsert,
    DynamicGroupResolveRequest,
    StaticGroupCreate,
    StaticGroupUpdate,
)


_dynamic_group_indexes_ready = False


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    deduped = []
    seen = set()
    for value in values:
        clean_value = str(value).strip()
        if not clean_value or clean_value in seen:
            continue
        seen.add(clean_value)
        deduped.append(clean_value)
    return deduped


def _normalize_tag_key(tag: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tag).strip().lower()).strip("_")
    return normalized or "untagged"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _group_response(group: dict) -> dict:
    group["id"] = str(group["_id"])
    group["recipient_count"] = len(group.get("recipient_ids", []))
    group.setdefault("type", "static")
    group.setdefault("recipient_ids", [])
    group.setdefault("recipient_emails", [])
    return group


def _normalized_full_name(first_name: str | None = None, last_name: str | None = None) -> str:
    return " ".join(
        part.strip().lower()
        for part in [str(first_name or "").strip(), str(last_name or "").strip()]
        if part and str(part).strip()
    ).strip()


def _display_name(recipient: dict) -> str:
    full_name = " ".join(
        part.strip()
        for part in [str(recipient.get("first_name") or "").strip(), str(recipient.get("last_name") or "").strip()]
        if part and part.strip()
    ).strip()
    return full_name or str(recipient.get("email") or "").strip()


def _days_since(reference: Optional[datetime], now: datetime) -> Optional[float]:
    if not reference:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max((now - reference).total_seconds() / 86400, 0.0)


async def _ensure_dynamic_group_indexes(db) -> None:
    global _dynamic_group_indexes_ready
    if _dynamic_group_indexes_ready:
        return

    await db["dynamic_group_preferences"].create_index(
        [("created_by", 1), ("tag_key", 1)],
        unique=True,
        name="dynamic_group_preference_unique",
    )
    _dynamic_group_indexes_ready = True


def _dynamic_group_preference_response(document: dict) -> dict:
    document["id"] = str(document["_id"])
    return document


def _calculate_dynamic_tag_score(
    *,
    recipient: dict,
    tag_key: str,
    tag_label: str,
    tag_stats: Optional[dict],
    min_interactions: int,
) -> dict:
    now = datetime.now(timezone.utc)
    engagement = recipient.get("engagement") or {}
    interaction_counts = engagement.get("tag_interaction_counts") or {}
    tag_scores = engagement.get("tag_scores") or {}

    base_interactions = int(interaction_counts.get(tag_key, 0) or 0)
    base_tag_score = float(tag_scores.get(tag_key, 0) or 0)
    stats = tag_stats or {}
    unique_open_count = int(stats.get("unique_open_count", 0) or 0)
    unique_click_count = int(stats.get("unique_click_count", 0) or 0)
    open_count = int(stats.get("open_count", 0) or 0)
    click_count = int(stats.get("click_count", 0) or 0)
    delivery_count = int(stats.get("delivery_count", 0) or 0)
    delivery_failure_count = int(stats.get("delivery_failure_count", 0) or 0)
    campaign_touchpoints = int(stats.get("campaign_touchpoints", 0) or 0)

    interaction_count = max(base_interactions, unique_open_count + unique_click_count, delivery_count)
    last_open_at = stats.get("last_open_at") or engagement.get("last_open_at")
    last_click_at = stats.get("last_click_at") or engagement.get("last_click_at")
    most_recent_touch = max([value for value in [last_open_at, last_click_at] if value], default=None)
    recency_days = _days_since(most_recent_touch, now)

    tag_score_points = min(math.log1p(base_tag_score) / math.log1p(40), 1.0) * 38
    interaction_points = min(math.log1p(interaction_count) / math.log1p(max(min_interactions + 8, 9)), 1.0) * 18
    open_points = min(math.log1p(open_count + unique_open_count) / math.log1p(20), 1.0) * 12
    click_points = min(math.log1p(click_count + (unique_click_count * 2)) / math.log1p(18), 1.0) * 18
    relationship_points = min(math.log1p(campaign_touchpoints) / math.log1p(12), 1.0) * 8

    if recency_days is None:
        recency_points = 0.0
    elif recency_days <= 3:
        recency_points = 12.0
    elif recency_days <= 7:
        recency_points = 9.0
    elif recency_days <= 14:
        recency_points = 6.0
    elif recency_days <= 30:
        recency_points = 3.0
    else:
        recency_points = 0.0

    total_delivery_attempts = delivery_count + delivery_failure_count
    if total_delivery_attempts > 0:
        reliability_points = (delivery_count / total_delivery_attempts) * 6
    else:
        reliability_points = 3.0

    status_points = 4.0 if str(recipient.get("status", "active")).lower() == "active" else -20.0
    consent_flags = recipient.get("consent_flags") or {}
    consent_points = 3.0 if consent_flags.get("email", True) else -10.0

    score = tag_score_points + interaction_points + open_points + click_points
    score += relationship_points + recency_points + reliability_points + status_points + consent_points
    score = _clamp(score, 0.0, 100.0)

    return {
        "tag": tag_label,
        "tag_key": tag_key,
        "dynamic_score": round(score, 2),
        "tag_score": round(base_tag_score, 2),
        "interaction_count": interaction_count,
        "unique_open_count": unique_open_count,
        "unique_click_count": unique_click_count,
        "last_open_at": last_open_at,
        "last_click_at": last_click_at,
        "campaign_touchpoints": campaign_touchpoints,
        "delivery_count": delivery_count,
        "eligible": interaction_count >= min_interactions,
    }


async def list_dynamic_group_preferences(user_id: str) -> list[dict]:
    db = get_database()
    await _ensure_dynamic_group_indexes(db)
    prefs = await db["dynamic_group_preferences"].find({"created_by": user_id}).sort("tag", 1).to_list(length=500)
    return [_dynamic_group_preference_response(pref) for pref in prefs]


async def upsert_dynamic_group_preference(user_id: str, payload: DynamicGroupPreferenceUpsert) -> dict:
    db = get_database()
    await _ensure_dynamic_group_indexes(db)
    tag = payload.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag is required")

    now = datetime.now(timezone.utc)
    preference = DynamicGroupPreferenceDB(
        created_by=user_id,
        tag=tag,
        tag_key=_normalize_tag_key(tag),
        top_k=payload.top_k,
        min_interactions=payload.min_interactions,
        updated_at=now,
    )
    preference_dict = preference.model_dump(by_alias=True, exclude={"id"})
    preference_dict["updated_at"] = now

    await db["dynamic_group_preferences"].update_one(
        {"created_by": user_id, "tag_key": preference.tag_key},
        {
            "$set": {
                "tag": preference.tag,
                "tag_key": preference.tag_key,
                "top_k": preference.top_k,
                "min_interactions": preference.min_interactions,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_by": user_id,
                "created_at": now,
            },
        },
        upsert=True,
    )
    stored = await db["dynamic_group_preferences"].find_one({"created_by": user_id, "tag_key": preference.tag_key})
    return _dynamic_group_preference_response(stored)


async def _get_dynamic_group_preference(user_id: str, tag_key: str) -> Optional[dict]:
    db = get_database()
    await _ensure_dynamic_group_indexes(db)
    return await db["dynamic_group_preferences"].find_one({"created_by": user_id, "tag_key": tag_key})


async def resolve_dynamic_group_request(user_id: str, request: DynamicGroupResolveRequest) -> dict:
    db = get_database()
    tag = request.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag is required for dynamic groups")

    tag_key = _normalize_tag_key(tag)
    saved_preference = await _get_dynamic_group_preference(user_id, tag_key)
    used_saved_top_k = request.top_k is None and saved_preference is not None

    top_k = request.top_k if request.top_k is not None else (saved_preference.get("top_k") if saved_preference else None)
    if top_k is None:
        raise HTTPException(
            status_code=400,
            detail=f"Top K is required for tag '{tag}' because no saved dynamic-group preference exists yet",
        )

    min_interactions = (
        request.min_interactions
        if request.min_interactions is not None
        else (saved_preference.get("min_interactions") if saved_preference else 1)
    )

    recipients = await db["recipients"].find({"user_id": user_id}).to_list(length=5000)
    recipient_stats_rows = await db["campaign_recipient_stats"].aggregate([
        {"$match": {"owner_user_id": user_id, "campaign_tag_keys": tag_key}},
        {"$group": {
            "_id": "$recipient_email",
            "campaign_touchpoints": {"$sum": 1},
            "delivery_count": {"$sum": {"$ifNull": ["$delivery_count", 0]}},
            "delivery_failure_count": {"$sum": {"$ifNull": ["$delivery_failure_count", 0]}},
            "open_count": {"$sum": {"$ifNull": ["$open_count", 0]}},
            "click_count": {"$sum": {"$ifNull": ["$click_count", 0]}},
            "unique_open_count": {"$sum": {"$ifNull": ["$unique_open_count", 0]}},
            "unique_click_count": {"$sum": {"$ifNull": ["$unique_click_count", 0]}},
            "last_open_at": {"$max": "$last_open_at"},
            "last_click_at": {"$max": "$last_click_at"},
        }},
    ]).to_list(length=5000)
    recipient_stats_map = {str(row["_id"]): row for row in recipient_stats_rows}

    scored_recipients = []
    for recipient in recipients:
        score_info = _calculate_dynamic_tag_score(
            recipient=recipient,
            tag_key=tag_key,
            tag_label=tag,
            tag_stats=recipient_stats_map.get(recipient["email"]),
            min_interactions=min_interactions,
        )
        if not score_info["eligible"]:
            continue
        scored_recipients.append({
            "id": str(recipient["_id"]),
            "email": recipient["email"],
            "name": _display_name(recipient),
            "dynamic_score": score_info["dynamic_score"],
            "tag_score": score_info["tag_score"],
            "interaction_count": score_info["interaction_count"],
            "delivery_count": score_info["delivery_count"],
            "campaign_touchpoints": score_info["campaign_touchpoints"],
            "unique_open_count": score_info["unique_open_count"],
            "unique_click_count": score_info["unique_click_count"],
            "last_open_at": score_info["last_open_at"],
            "last_click_at": score_info["last_click_at"],
        })

    scored_recipients.sort(
        key=lambda recipient: (
            -recipient["dynamic_score"],
            -recipient["interaction_count"],
            recipient["email"].lower(),
        )
    )
    selected_recipients = scored_recipients[:top_k]

    return {
        "tag": tag,
        "tag_key": tag_key,
        "top_k": top_k,
        "min_interactions": min_interactions,
        "used_saved_top_k": used_saved_top_k,
        "total_eligible": len(scored_recipients),
        "recipients": selected_recipients,
    }


async def resolve_dynamic_group_payload(user_id: str, requests: list[DynamicGroupResolveRequest]) -> list[dict]:
    resolved_groups = []
    for request in requests:
        resolved_groups.append(await resolve_dynamic_group_request(user_id, request))
    return resolved_groups


async def resolve_dynamic_group_emails(user_id: str, requests: list[DynamicGroupResolveRequest]) -> tuple[list[str], list[dict]]:
    resolved_groups = await resolve_dynamic_group_payload(user_id, requests)

    emails = _dedupe_strings(
        recipient["email"]
        for group in resolved_groups
        for recipient in group.get("recipients", [])
    )

    for original_request, resolved_group in zip(requests, resolved_groups):
        if original_request.top_k is not None:
            await upsert_dynamic_group_preference(
                user_id,
                DynamicGroupPreferenceUpsert(
                    tag=resolved_group["tag"],
                    top_k=resolved_group["top_k"],
                    min_interactions=resolved_group["min_interactions"],
                ),
            )

    return emails, resolved_groups


async def _resolve_recipients(user_id: str, recipient_ids: Iterable[str]) -> tuple[List[str], List[str]]:
    recipient_ids = _dedupe_strings(recipient_ids)
    if not recipient_ids:
        return [], []

    object_ids = []
    for recipient_id in recipient_ids:
        if not ObjectId.is_valid(recipient_id):
            raise HTTPException(status_code=400, detail=f"Invalid recipient ID: {recipient_id}")
        object_ids.append(ObjectId(recipient_id))

    db = get_database()
    recipients = await db["recipients"].find(
        {"_id": {"$in": object_ids}, "user_id": user_id},
        {"email": 1},
    ).to_list(length=len(object_ids))

    recipients_by_id = {str(recipient["_id"]): recipient for recipient in recipients}
    missing_ids = [recipient_id for recipient_id in recipient_ids if recipient_id not in recipients_by_id]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Recipients not found: {', '.join(missing_ids)}")

    recipient_emails = [recipients_by_id[recipient_id]["email"] for recipient_id in recipient_ids]
    return recipient_ids, recipient_emails


async def _resolve_import_groups(
    user_id: str,
    group_ids: Iterable[str],
    *,
    exclude_group_id: str | None = None,
) -> tuple[List[str], List[str]]:
    group_ids = _dedupe_strings(group_ids)
    if not group_ids:
        return [], []

    if exclude_group_id and exclude_group_id in group_ids:
        raise HTTPException(status_code=400, detail="A static group cannot import itself")

    object_ids = []
    for group_id in group_ids:
        if not ObjectId.is_valid(group_id):
            raise HTTPException(status_code=400, detail=f"Invalid group ID: {group_id}")
        object_ids.append(ObjectId(group_id))

    db = get_database()
    groups = await db["groups"].find(
        {"_id": {"$in": object_ids}, "created_by": user_id, "type": "static"},
        {"recipient_ids": 1, "recipient_emails": 1},
    ).to_list(length=len(object_ids))

    groups_by_id = {str(group["_id"]): group for group in groups}
    missing_ids = [group_id for group_id in group_ids if group_id not in groups_by_id]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Static groups not found: {', '.join(missing_ids)}")

    imported_recipient_ids = []
    imported_recipient_emails = []
    for group_id in group_ids:
        group = groups_by_id[group_id]
        imported_recipient_ids.extend(group.get("recipient_ids", []))
        imported_recipient_emails.extend(group.get("recipient_emails", []))

    return _dedupe_strings(imported_recipient_ids), _dedupe_strings(imported_recipient_emails)


async def create_static_group(user_id: str, group_data: StaticGroupCreate) -> dict:
    db = get_database()
    name = group_data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")

    existing = await db["groups"].find_one({"created_by": user_id, "name": name, "type": "static"})
    if existing:
        raise HTTPException(status_code=400, detail="A static group with this name already exists")

    direct_recipient_ids, direct_recipient_emails = await _resolve_recipients(user_id, group_data.recipient_ids)
    imported_recipient_ids, imported_recipient_emails = await _resolve_import_groups(user_id, group_data.import_group_ids)
    recipient_ids = _dedupe_strings([*imported_recipient_ids, *direct_recipient_ids])
    recipient_emails = _dedupe_strings([*imported_recipient_emails, *direct_recipient_emails])
    group = GroupDB(
        name=name,
        description=group_data.description,
        recipient_ids=recipient_ids,
        recipient_emails=recipient_emails,
        created_by=user_id,
    )

    result = await db["groups"].insert_one(group.model_dump(by_alias=True, exclude={"id"}))
    created = await db["groups"].find_one({"_id": result.inserted_id})
    return _group_response(created)


async def list_static_groups(user_id: str) -> list[dict]:
    db = get_database()
    groups = await db["groups"].find({"created_by": user_id, "type": "static"}).sort("created_at", -1).to_list(length=500)
    return [_group_response(group) for group in groups]


async def get_static_group(user_id: str, group_id: str) -> dict:
    if not ObjectId.is_valid(group_id):
        raise HTTPException(status_code=400, detail="Invalid group ID")

    db = get_database()
    group = await db["groups"].find_one({"_id": ObjectId(group_id), "created_by": user_id, "type": "static"})
    if not group:
        raise HTTPException(status_code=404, detail="Static group not found")
    return _group_response(group)


async def update_static_group(user_id: str, group_id: str, group_data: StaticGroupUpdate) -> dict:
    if not ObjectId.is_valid(group_id):
        raise HTTPException(status_code=400, detail="Invalid group ID")

    db = get_database()
    existing = await db["groups"].find_one({"_id": ObjectId(group_id), "created_by": user_id, "type": "static"})
    if not existing:
        raise HTTPException(status_code=404, detail="Static group not found")

    update_doc = {"updated_at": datetime.now(timezone.utc)}
    if group_data.name is not None:
        name = group_data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Group name is required")
        duplicate = await db["groups"].find_one(
            {
                "_id": {"$ne": ObjectId(group_id)},
                "created_by": user_id,
                "name": name,
                "type": "static",
            }
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="A static group with this name already exists")
        update_doc["name"] = name

    if group_data.description is not None:
        update_doc["description"] = group_data.description

    if group_data.recipient_ids is not None or group_data.import_group_ids is not None:
        direct_recipient_ids, direct_recipient_emails = await _resolve_recipients(
            user_id,
            group_data.recipient_ids if group_data.recipient_ids is not None else existing.get("recipient_ids", []),
        )
        imported_recipient_ids, imported_recipient_emails = await _resolve_import_groups(
            user_id,
            group_data.import_group_ids if group_data.import_group_ids is not None else [],
            exclude_group_id=group_id,
        )
        recipient_ids = _dedupe_strings([*imported_recipient_ids, *direct_recipient_ids])
        recipient_emails = _dedupe_strings([*imported_recipient_emails, *direct_recipient_emails])
        update_doc["recipient_ids"] = recipient_ids
        update_doc["recipient_emails"] = recipient_emails

    await db["groups"].update_one(
        {"_id": ObjectId(group_id), "created_by": user_id, "type": "static"},
        {"$set": update_doc},
    )
    updated = await db["groups"].find_one({"_id": ObjectId(group_id)})
    return _group_response(updated)


async def delete_static_group(user_id: str, group_id: str) -> None:
    if not ObjectId.is_valid(group_id):
        raise HTTPException(status_code=400, detail="Invalid group ID")

    db = get_database()
    result = await db["groups"].delete_one({"_id": ObjectId(group_id), "created_by": user_id, "type": "static"})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Static group not found")


async def resolve_static_group_emails(user_id: str, group_ids: Iterable[str]) -> list[str]:
    group_ids = _dedupe_strings(group_ids)
    if not group_ids:
        return []

    object_ids = []
    for group_id in group_ids:
        if not ObjectId.is_valid(group_id):
            raise HTTPException(status_code=400, detail=f"Invalid group ID: {group_id}")
        object_ids.append(ObjectId(group_id))

    db = get_database()
    groups = await db["groups"].find(
        {"_id": {"$in": object_ids}, "created_by": user_id, "type": "static"},
        {"recipient_emails": 1},
    ).to_list(length=len(object_ids))

    groups_by_id = {str(group["_id"]): group for group in groups}
    missing_ids = [group_id for group_id in group_ids if group_id not in groups_by_id]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Static groups not found: {', '.join(missing_ids)}")

    emails = []
    for group_id in group_ids:
        emails.extend(groups_by_id[group_id].get("recipient_emails", []))
    return _dedupe_strings(emails)


async def import_static_group_csv(user_id: str, file: UploadFile) -> dict:
    db = get_database()
    content = await file.read()

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be valid UTF-8 encoded CSV")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must include headers. Supported columns: email, full_name, first_name, last_name",
        )

    recipients = await db["recipients"].find(
        {"user_id": user_id},
        {"email": 1, "first_name": 1, "last_name": 1},
    ).to_list(length=5000)

    recipients_by_email = {
        str(recipient.get("email", "")).strip().lower(): recipient
        for recipient in recipients
        if str(recipient.get("email", "")).strip()
    }
    recipients_by_name = defaultdict(list)
    for recipient in recipients:
        normalized_name = _normalized_full_name(recipient.get("first_name"), recipient.get("last_name"))
        if normalized_name:
            recipients_by_name[normalized_name].append(recipient)

    matched_ids = []
    matched_emails = []
    unmatched_rows = []
    seen_ids = set()
    skipped_count = 0

    for line_number, row in enumerate(reader, start=2):
        cleaned_row = {str(key or "").strip().lower(): str(value or "").strip() for key, value in row.items()}
        email = cleaned_row.get("email", "").lower()
        full_name = cleaned_row.get("full_name", "")
        first_name = cleaned_row.get("first_name", "")
        last_name = cleaned_row.get("last_name", "")

        matched_recipient = None
        if email:
            matched_recipient = recipients_by_email.get(email)
        else:
            normalized_name = _normalized_full_name(
                full_name or first_name,
                "" if full_name else last_name,
            )
            possible_matches = recipients_by_name.get(normalized_name, [])
            if len(possible_matches) == 1:
                matched_recipient = possible_matches[0]
            elif len(possible_matches) > 1:
                unmatched_rows.append(f"Line {line_number}: multiple recipients matched '{normalized_name}'")
                skipped_count += 1
                continue

        if not matched_recipient:
            descriptor = email or full_name or _normalized_full_name(first_name, last_name) or "empty row"
            unmatched_rows.append(f"Line {line_number}: no recipient matched '{descriptor}'")
            skipped_count += 1
            continue

        recipient_id = str(matched_recipient["_id"])
        if recipient_id in seen_ids:
            skipped_count += 1
            continue

        seen_ids.add(recipient_id)
        matched_ids.append(recipient_id)
        matched_emails.append(matched_recipient["email"])

    return {
        "matched_recipient_ids": matched_ids,
        "matched_recipient_emails": matched_emails,
        "matched_count": len(matched_ids),
        "skipped_count": skipped_count,
        "unmatched_rows": unmatched_rows,
    }
