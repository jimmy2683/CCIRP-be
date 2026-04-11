from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class DynamicGroupRequest(BaseModel):
    tag: str = Field(..., min_length=1, description="Dynamic audience tag")
    top_k: Optional[int] = Field(default=None, gt=0, description="Preferred audience size")
    min_interactions: Optional[int] = Field(default=None, ge=1, description="Minimum interactions required to qualify")

class CampaignCreate(BaseModel):
    name: str = Field(..., description="Name of the campaign")
    subject: str = Field(..., description="Email or message subject")
    template_id: str = Field(..., description="ID of the selected template")
    channels: List[str] = Field(default_factory=lambda: ["email"], description="Delivery channels for this campaign")
    tags: List[str] = Field(default_factory=list, description="User-defined campaign tags")
    group_ids: List[str] = Field(default_factory=list, description="Static group IDs included in this campaign")
    dynamic_groups: List[DynamicGroupRequest] = Field(default_factory=list, description="Dynamic group requests resolved at send time")
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
    dynamic_groups: List[Dict[str, Any]] = Field(default_factory=list)
    status: str
    recipients: List[str]
    merge_data: Dict[str, str] = {}
    scheduled_at: Optional[datetime] = None
    queue_summary: Optional[Dict[str, Any]] = None
    delivery_summary: Optional[Dict[str, Any]] = None
    priority_algorithm_version: Optional[str] = None
    queue_prepared_at: Optional[datetime] = None
    dispatch_started_at: Optional[datetime] = None
    dispatch_completed_at: Optional[datetime] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
