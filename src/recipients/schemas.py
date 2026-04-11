from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr
from datetime import datetime
from src.models import PyObjectId

class ConsentFlagsSchema(BaseModel):
    email: bool = True
    sms: bool = False
    whatsapp: bool = False

class EngagementStatsSchema(BaseModel):
    open_count_total: int = 0
    click_count_total: int = 0
    unique_open_campaigns: List[str] = []
    unique_click_campaigns: List[str] = []
    clicked_domains: List[str] = []
    tag_scores: Dict[str, int] = {}
    topic_scores: Dict[str, int] = {}
    last_open_at: Optional[datetime] = None
    last_click_at: Optional[datetime] = None

class RecipientCreate(BaseModel):
    email: EmailStr
    phone: str
    first_name: str
    last_name: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    consent_flags: Optional[ConsentFlagsSchema] = None

class RecipientUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    consent_flags: Optional[ConsentFlagsSchema] = None
    status: Optional[str] = None

class RecipientResponse(BaseModel):
    id: PyObjectId
    user_id: str
    email: EmailStr
    phone: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    attributes: Dict[str, Any]
    tags: List[str]
    consent_flags: ConsentFlagsSchema
    status: str
    engagement: EngagementStatsSchema
    created_at: datetime
    updated_at: datetime
