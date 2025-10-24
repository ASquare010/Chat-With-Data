from uuid import UUID
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from backend_db.models import Sender


class UserCreate(BaseModel):
    email: Optional[str]
    display_name: Optional[str]


class UserRead(BaseModel):
    id: UUID
    email: Optional[str]
    display_name: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


class MessageCreate(BaseModel):
    sender: Sender
    content: Optional[str] = None
    is_image: bool = False
    base64_image: Optional[str] = None
    metadata: Optional[dict] = None


class MessageRead(BaseModel):
    id: UUID
    thread_id: UUID
    sender: Sender
    content: Optional[str]
    is_image: bool
    base64_image: Optional[str]
    metadata: Optional[dict]
    created_at: datetime

    class Config:
        orm_mode = True


class ThreadCreate(BaseModel):
    title: Optional[str] = None
    metadata: Optional[dict] = None


class ThreadRead(BaseModel):
    id: UUID
    user_id: UUID
    title: Optional[str]
    metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime
    messages: List[MessageRead] = []

    class Config:
        orm_mode = True


class Text2SQLOutput(BaseModel):
    sql: list[str]
