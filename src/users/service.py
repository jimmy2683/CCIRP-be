from datetime import datetime, timezone
from typing import List, Optional
from src.database import get_database
from src.users.models import UserDB

class UserService:
    @staticmethod
    async def list_users() -> List[dict]:
        db = get_database()
        cursor = db.users.find({"phone": {"$nin": [None, ""]}})
        users = await cursor.to_list(length=1000)
        for user in users:
            user["id"] = str(user["_id"])
        return users

    @staticmethod
    async def sync_user_recipient(user: dict, owner_user_id: Optional[str] = None) -> None:
        db = get_database()
        if db is None:
            return

        user_id = owner_user_id or str(user.get("_id") or user.get("id") or "")
        if not user_id:
            return

        full_name = str(user.get("full_name") or "").strip()
        first_name = full_name.split(" ")[0] if full_name else str(user.get("email", "")).split("@")[0]
        last_name = full_name.split(" ", 1)[1] if " " in full_name else None
        now = datetime.now(timezone.utc)

        await db["recipients"].update_one(
            {"user_id": user_id, "email": user["email"]},
            {
                "$set": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": user.get("phone"),
                    "status": "active",
                    "updated_at": now,
                    "attributes": {},
                },
                "$setOnInsert": {
                    "user_id": user_id,
                    "email": user["email"],
                    "tags": ["user-account"],
                    "consent_flags": {"email": True, "sms": False, "whatsapp": False},
                    "engagement": {
                        "open_count_total": 0,
                        "click_count_total": 0,
                        "unique_open_campaigns": [],
                        "unique_click_campaigns": [],
                        "clicked_domains": [],
                        "tag_scores": {},
                        "topic_scores": {},
                        "last_open_at": None,
                        "last_click_at": None,
                    },
                    "created_at": now,
                },
            },
            upsert=True,
        )
