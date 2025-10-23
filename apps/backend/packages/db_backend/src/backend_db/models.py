# models.py
import uuid
import enum
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    Text,
    Enum as SAEnum,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Sender(enum.Enum):
    human = "human"
    assistant = "assistant"
    system = "system"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=True, index=True)
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    threads = relationship(
        "ChatThread", back_populates="user", cascade="all, delete-orphan"
    )


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata = Column(JSONB, nullable=True, default={})

    user = relationship("User", back_populates="threads")
    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender = Column(SAEnum(Sender, name="sender_enum"), nullable=False)
    content = Column(Text, nullable=True)  # textual content
    is_image = Column(Boolean, nullable=False, default=False)
    base64_image = Column(
        Text, nullable=True
    )  # store small images as base64; prefer object storage for large files
    metadata = Column(
        JSONB, nullable=True, default={}
    )  # e.g. {"tokens": 123, "model": "gpt-5"}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("ChatThread", back_populates="messages")
