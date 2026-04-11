from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StaticGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Static group name")
    description: Optional[str] = None
    recipient_ids: List[str] = Field(default_factory=list)
    import_group_ids: List[str] = Field(default_factory=list)


class StaticGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    recipient_ids: Optional[List[str]] = None
    import_group_ids: Optional[List[str]] = None


class StaticGroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    type: str = "static"
    recipient_ids: List[str]
    recipient_emails: List[str]
    recipient_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
