from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str


class ConversationMeta(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationFull(ConversationMeta):
    messages: List[dict]
