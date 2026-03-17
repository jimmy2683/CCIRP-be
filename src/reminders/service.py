from typing import List, Optional
from bson import ObjectId
from datetime import datetime
from src.database import get_database
from src.reminders.schemas import ReminderCreate, ReminderUpdate

class ReminderService:
    @staticmethod
    async def create_reminder(reminder_data: ReminderCreate, user_id: str) -> dict:
        db = get_database()
        new_reminder = reminder_data.model_dump()
        new_reminder["user_id"] = user_id
        new_reminder["status"] = "Pending"
        new_reminder["created_at"] = datetime.utcnow()
        new_reminder["updated_at"] = datetime.utcnow()
        
        result = await db.reminders.insert_one(new_reminder)
        new_reminder["_id"] = str(result.inserted_id)
        return new_reminder

    @staticmethod
    async def get_reminders(user_id: str) -> List[dict]:
        db = get_database()
        cursor = db.reminders.find({"user_id": user_id})
        documents = await cursor.to_list(length=100)
        reminders = []
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            reminders.append(doc)
        return reminders

    @staticmethod
    async def get_reminder_by_id(reminder_id: str, user_id: str) -> Optional[dict]:
        db = get_database()
        if not ObjectId.is_valid(reminder_id):
            return None
        document = await db.reminders.find_one({"_id": ObjectId(reminder_id), "user_id": user_id})
        if document:
            document["_id"] = str(document["_id"])
        return document

    @staticmethod
    async def update_reminder(reminder_id: str, reminder_data: ReminderUpdate, user_id: str) -> Optional[dict]:
        db = get_database()
        if not ObjectId.is_valid(reminder_id):
            return None
            
        update_data = {k: v for k, v in reminder_data.model_dump().items() if v is not None}
        if not update_data:
            return await ReminderService.get_reminder_by_id(reminder_id, user_id)
            
        update_data["updated_at"] = datetime.utcnow()
        
        result = await db.reminders.update_one(
            {"_id": ObjectId(reminder_id), "user_id": user_id},
            {"$set": update_data}
        )
        
        if result.matched_count:
            return await ReminderService.get_reminder_by_id(reminder_id, user_id)
        return None

    @staticmethod
    async def delete_reminder(reminder_id: str, user_id: str) -> bool:
        db = get_database()
        if not ObjectId.is_valid(reminder_id):
            return False
        result = await db.reminders.delete_one({"_id": ObjectId(reminder_id), "user_id": user_id})
        return result.deleted_count > 0
