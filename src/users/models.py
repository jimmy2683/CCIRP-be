from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr

class UserDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    email: EmailStr
    hashed_password: str
    full_name: str
    role: str = "user"
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
