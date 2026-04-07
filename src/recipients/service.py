from bson import ObjectId
from fastapi import HTTPException
from src.database import get_database
from src.recipients.models import RecipientDB
from src.recipients.schemas import RecipientCreate, RecipientUpdate
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone
from fastapi import UploadFile
import math
import csv
import io

async def import_csv(user_id: str, file: UploadFile) -> dict:
    db = get_database()
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be valid UTF-8 encoded CSV")
    
    reader = csv.DictReader(io.StringIO(text))
    
    success_count = 0
    skipped_count = 0
    errors = []
    
    for row in reader:
        cleaned_row = {k.strip().lower() if k else '': v for k, v in row.items()}
        email = cleaned_row.get("email", "").strip()
        if not email:
            continue
            
        existing = await db.recipients.find_one({"user_id": user_id, "email": email})
        if existing:
            skipped_count += 1
            continue
            
        tags = [t.strip() for t in cleaned_row.get("tags", "").split(",") if t.strip()]
        
        recipient_dict = {
            "user_id": user_id,
            "email": email,
            "first_name": cleaned_row.get("first_name", email.split('@')[0]).strip(),
            "last_name": cleaned_row.get("last_name", "").strip() or None,
            "phone": cleaned_row.get("phone", "").strip() or None,
            "tags": tags,
            "attributes": {},
            "consent_flags": {"email": True, "sms": False, "whatsapp": False},
        }
        
        new_recipient = RecipientDB(**recipient_dict)
        try:
            await db.recipients.insert_one(new_recipient.model_dump(by_alias=True, exclude={"id"}))
            success_count += 1
        except Exception as e:
            errors.append(f"Error importing {email}: {str(e)}")
            
    return {"success": success_count, "skipped": skipped_count, "errors": errors}

async def create_recipient(user_id: str, recipient_data: RecipientCreate) -> RecipientDB:
    db = get_database()
    collection = db.recipients

    existing = await collection.find_one({"user_id": user_id, "email": recipient_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Recipient with this email already exists")

    recipient_dict = recipient_data.model_dump(exclude_unset=True)
    recipient_dict["user_id"] = user_id
    
    if "attributes" not in recipient_dict or recipient_dict["attributes"] is None:
        recipient_dict["attributes"] = {}
    if "tags" not in recipient_dict or recipient_dict["tags"] is None:
        recipient_dict["tags"] = []
    if "consent_flags" not in recipient_dict or recipient_dict["consent_flags"] is None:
        recipient_dict["consent_flags"] = {"email": True, "sms": False, "whatsapp": False}

    new_recipient = RecipientDB(**recipient_dict)
    
    try:
        result = await collection.insert_one(new_recipient.model_dump(by_alias=True, exclude={"id"}))
        created_recipient = await collection.find_one({"_id": result.inserted_id})
        return RecipientDB(**created_recipient)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_recipients(user_id: str, skip: int = 0, limit: int = 100) -> list[RecipientDB]:
    db = get_database()
    cursor = db.recipients.find({"user_id": user_id}).skip(skip).limit(limit)
    recipients = await cursor.to_list(length=limit)
    return [RecipientDB(**rec) for rec in recipients]

async def get_recipient(user_id: str, recipient_id: str) -> RecipientDB:
    db = get_database()
    if not ObjectId.is_valid(recipient_id):
        raise HTTPException(status_code=400, detail="Invalid Recipient ID")
        
    recipient = await db.recipients.find_one({"_id": ObjectId(recipient_id), "user_id": user_id})
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
        
    return RecipientDB(**recipient)

async def update_recipient(user_id: str, recipient_id: str, update_data: RecipientUpdate) -> RecipientDB:
    db = get_database()
    if not ObjectId.is_valid(recipient_id):
        raise HTTPException(status_code=400, detail="Invalid Recipient ID")

    existing = await db.recipients.find_one({"_id": ObjectId(recipient_id), "user_id": user_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Recipient not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        return RecipientDB(**existing)

    update_dict["updated_at"] = datetime.now(timezone.utc)
    
    if "email" in update_dict:
        email_check = await db.recipients.find_one({
            "user_id": user_id, 
            "email": update_dict["email"], 
            "_id": {"$ne": ObjectId(recipient_id)}
        })
        if email_check:
            raise HTTPException(status_code=400, detail="Another recipient with this email already exists")

    await db.recipients.update_one(
        {"_id": ObjectId(recipient_id), "user_id": user_id},
        {"$set": update_dict}
    )

    updated = await db.recipients.find_one({"_id": ObjectId(recipient_id)})
    return RecipientDB(**updated)

async def delete_recipient(user_id: str, recipient_id: str):
    db = get_database()
    if not ObjectId.is_valid(recipient_id):
        raise HTTPException(status_code=400, detail="Invalid Recipient ID")

    result = await db.recipients.delete_one({"_id": ObjectId(recipient_id), "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    return True
