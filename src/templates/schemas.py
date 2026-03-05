from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from src.models import PyObjectId

class TemplateBase(BaseModel):
    name: str = Field(..., example="Assignment Reminder")
    category: str = Field(..., example="Academic")
    channel: str = Field(..., example="Email")
    subject: Optional[str] = Field(None, example="Assignment Due Reminder")
    body_html: str = Field(..., example="<p>Hello {{name}}...</p>")
    design_json: Optional[Any] = Field(None, description="JSON representing visual builder layout blocks")
    is_common: bool = Field(default=False, description="If true, template is visible to all users; if false, only visible to creator")

class TemplateCreate(TemplateBase):
    pass

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    channel: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    design_json: Optional[Any] = None
    is_common: Optional[bool] = None

class Template(TemplateBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    created_by: Optional[str] = Field(None, description="User ID of the template creator")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "_id": "60d5ecb8b48777ae680ffdd2",
                "name": "Assignment Reminder",
                "category": "Academic",
                "channel": "Email",
                "subject": "Assignment Due Reminder",
                "body_html": "<p>Hello {{name}}...</p>",
                "created_by": "user_id_123",
                "is_common": False,
                "version": 1
            }
        }

class TemplatePreviewRequest(BaseModel):
    template_id: str
    sample_data: dict

class TestSendRequest(BaseModel):
    email: str
    sample_data: Optional[dict] = None
