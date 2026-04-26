from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class ConversationDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    title: str
    messages: List[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
