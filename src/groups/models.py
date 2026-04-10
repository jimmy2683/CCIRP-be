from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class GroupDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    description: Optional[str] = None
    type: str = "static"
    recipient_ids: List[str] = Field(default_factory=list)
    recipient_emails: List[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
