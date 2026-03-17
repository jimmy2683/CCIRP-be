from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from src.models import PyObjectId

class ReminderBase(BaseModel):
    title: str = Field(..., example="Lunch with Team")
    description: Optional[str] = Field(None, example="Discuss the new project architecture")
    remind_at: datetime = Field(..., example="2024-03-20T12:00:00")
    channel: str = Field(default="Email", example="Email") # Email, SMS, Push
    priority: str = Field(default="Medium", example="High") # Low, Medium, High

class ReminderCreate(ReminderBase):
    pass

class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    remind_at: Optional[datetime] = None
    channel: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None # Pending, Sent, Cancelled

class Reminder(ReminderBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: str = Field(..., description="User ID of the reminder owner")
    status: str = Field(default="Pending")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "_id": "60d5ecb8b48777ae680ffdd2",
                "user_id": "user_123",
                "title": "Lunch with Team",
                "description": "Discuss the new project architecture",
                "remind_at": "2024-03-20T12:00:00",
                "channel": "Email",
                "priority": "Medium",
                "status": "Pending",
                "created_at": "2024-03-17T22:00:00",
                "updated_at": "2024-03-17T22:00:00"
            }
        }
