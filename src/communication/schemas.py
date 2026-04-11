from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime

class CampaignCreate(BaseModel):
    name: str = Field(..., description="Name of the campaign")
    subject: str = Field(..., description="Email or message subject")
    template_id: str = Field(..., description="ID of the selected template")
    channels: List[str] = Field(default_factory=lambda: ["email"], description="Delivery channels for this campaign")
    tags: List[str] = Field(default_factory=list, description="User-defined campaign tags")
    group_ids: List[str] = Field(default_factory=list, description="Static group IDs included in this campaign")
    recipients: List[str] = Field(default_factory=list, description="List of recipient emails or IDs")
    merge_data: Dict[str, str] = Field(default_factory=dict, description="Values for template merge fields")
    scheduled_at: Optional[datetime] = Field(default=None, description="When to send the campaign")

class CampaignResponse(BaseModel):
    id: str
    name: str
    subject: str
    template_id: str
    channels: List[str] = Field(default_factory=lambda: ["email"])
    tags: List[str] = Field(default_factory=list)
    group_ids: List[str] = Field(default_factory=list)
    status: str
    recipients: List[str]
    merge_data: Dict[str, str] = {}
    scheduled_at: Optional[datetime] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
