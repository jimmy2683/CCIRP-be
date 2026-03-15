from typing import List, Optional
from src.database import get_database
from src.users.models import UserDB

class UserService:
    @staticmethod
    async def list_users() -> List[dict]:
        db = get_database()
        cursor = db.users.find({})
        users = await cursor.to_list(length=1000)
        for user in users:
            user["id"] = str(user["_id"])
        return users
