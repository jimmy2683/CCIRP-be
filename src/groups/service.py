from datetime import datetime, timezone
from typing import Iterable, List

from bson import ObjectId
from fastapi import HTTPException

from src.database import get_database
from src.groups.models import GroupDB
from src.groups.schemas import StaticGroupCreate, StaticGroupUpdate


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


def _group_response(group: dict) -> dict:
    group["id"] = str(group["_id"])
    group["recipient_count"] = len(group.get("recipient_ids", []))
    group.setdefault("type", "static")
    group.setdefault("recipient_ids", [])
    group.setdefault("recipient_emails", [])
    return group


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
