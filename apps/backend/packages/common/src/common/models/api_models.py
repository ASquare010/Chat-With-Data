from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    metadata: Optional[dict] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    created_at: datetime


class Text2SQLOutput(BaseModel):
    sql: list[str]
