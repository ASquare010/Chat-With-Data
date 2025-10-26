# main.py
from uuid import UUID
import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from backend_db import crud, get_db
from backend_db.models import Sender
from agentic.chat_bot import ChatOrchestrator
from common.utils.postgres_client import PostgresClient
from common.models.api_models import (
    UserRead,
    ThreadRead,
    ThreadCreate,
    MessageCreate,
    MessageRead,
    UserCreate,
)

client = PostgresClient()
client.connect()
app = FastAPI(title="Chat Service")


@app.post("/users", response_model=UserRead)
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await crud.create_user(
        db, email=user_in.email, display_name=user_in.display_name
    )
    return user


@app.post("/users/{user_id}/threads", response_model=ThreadRead)
async def create_thread_for_user(
    user_id: UUID, thread_in: ThreadCreate, db: AsyncSession = Depends(get_db)
):
    user = await crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    thread = await crud.create_thread(
        db,
        user_id=user_id,
        title=thread_in.title,
        extra_metadata=thread_in.extra_metadata,
    )
    return thread


@app.post("/threads/{thread_id}/messages", response_model=MessageRead)
async def post_message(
    thread_id: UUID,
    message_in: MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    thread = await crud.get_thread_with_messages(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await crud.create_message(
        db,
        thread_id=thread_id,
        sender=message_in.sender,
        content=message_in.content,
        is_image=message_in.is_image,
        base64_image=message_in.base64_image,
        extra_metadata=message_in.extra_metadata,
    )
    try:
        schema_metadata = await crud.get_user_schema_metadata(db, thread.user_id)
        print("metadata", schema_metadata)
        agent = ChatOrchestrator(client, schema_metadata)
        ai_text = await agent.ainvoke(message_in.content or "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {e}") from e

    return await crud.create_message(
        db,
        thread_id=thread_id,
        sender=Sender.assistant,
        content=ai_text,
        is_image=bool(getattr(agent, "base64_image", "")),
        base64_image=getattr(agent, "base64_image", None),
        extra_metadata={"from_agent": True},
    )


@app.get("/threads/{thread_id}", response_model=ThreadRead)
async def load_thread(thread_id: UUID, db: AsyncSession = Depends(get_db)):
    thread = await crud.get_thread_with_messages(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
