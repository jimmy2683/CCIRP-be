from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr
from src.models import PyObjectId

class ConsentFlags(BaseModel):
    email: bool = True
    sms: bool = False
    whatsapp: bool = False

class EngagementStats(BaseModel):
    open_count_total: int = 0
    click_count_total: int = 0
    unique_open_campaigns: List[str] = Field(default_factory=list)
    unique_click_campaigns: List[str] = Field(default_factory=list)
    clicked_domains: List[str] = Field(default_factory=list)
    tag_scores: Dict[str, int] = Field(default_factory=dict)
    tag_interaction_counts: Dict[str, int] = Field(default_factory=dict)
    topic_scores: Dict[str, int] = Field(default_factory=dict)
    last_open_at: Optional[datetime] = None
    last_click_at: Optional[datetime] = None

class RecipientDB(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    user_id: str
    email: EmailStr
    phone: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    consent_flags: ConsentFlags = Field(default_factory=ConsentFlags)
    status: str = "active"
    engagement: EngagementStats = Field(default_factory=EngagementStats)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
