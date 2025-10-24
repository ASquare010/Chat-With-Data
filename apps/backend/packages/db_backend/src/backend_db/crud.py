# crud.py
from uuid import UUID
from typing import List
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from backend_db.models import User, ChatThread, Message


async def get_user(db: AsyncSession, user_id: UUID):
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, email: str = None, display_name: str = None):
    user = User(email=email, display_name=display_name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_thread(
    db: AsyncSession, user_id: UUID, title: str = None, metadata: dict = None
):
    thread = ChatThread(user_id=user_id, title=title, metadata=metadata or {})
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


async def create_message(
    db: AsyncSession,
    thread_id: UUID,
    sender,
    content: str = None,
    is_image: bool = False,
    base64_image: str = None,
    metadata: dict = None,
):
    msg = Message(
        thread_id=thread_id,
        sender=sender,
        content=content,
        is_image=is_image,
        base64_image=base64_image,
        metadata=metadata or {},
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_thread_with_messages(db: AsyncSession, thread_id: UUID):
    stmt = (
        select(ChatThread)
        .where(ChatThread.id == thread_id)
        .options(selectinload(ChatThread.messages))
    )
    res = await db.execute(stmt)
    return res.scalars().first()


async def list_threads_for_user(db: AsyncSession, user_id: UUID) -> List[ChatThread]:
    stmt = (
        select(ChatThread)
        .where(ChatThread.user_id == user_id)
        .order_by(ChatThread.updated_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()
