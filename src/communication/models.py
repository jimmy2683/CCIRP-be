from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class CampaignDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    subject: str
    template_id: str
    channels: List[str] = Field(default_factory=lambda: ["email"])
    tags: List[str] = Field(default_factory=list)
    group_ids: List[str] = Field(default_factory=list)
    dynamic_groups: List[Dict[str, Any]] = Field(default_factory=list)
    recipients: List[str] = Field(default_factory=list)
    merge_data: Dict[str, str] = Field(default_factory=dict)
    status: str = "draft"  # draft, queued, dispatching, scheduled, sent, partially_sent, failed
    scheduled_at: Optional[datetime] = None
    queue_summary: Optional[Dict[str, Any]] = None
    delivery_summary: Optional[Dict[str, Any]] = None
    priority_algorithm_version: Optional[str] = None
    queue_prepared_at: Optional[datetime] = None
    dispatch_started_at: Optional[datetime] = None
    dispatch_completed_at: Optional[datetime] = None
    created_by: str  # User ID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
