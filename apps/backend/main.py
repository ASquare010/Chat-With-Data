# main.py
import uvicorn
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from backend_db import crud, schemas, get_db


app = FastAPI(title="Chat Service")


@app.post("/users", response_model=schemas.UserRead)
async def create_user(user_in: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    user = await crud.create_user(
        db, email=user_in.email, display_name=user_in.display_name
    )
    return user


@app.post("/users/{user_id}/threads", response_model=schemas.ThreadRead)
async def create_thread_for_user(
    user_id: UUID, thread_in: schemas.ThreadCreate, db: AsyncSession = Depends(get_db)
):
    user = await crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    thread = await crud.create_thread(
        db, user_id=user_id, title=thread_in.title, metadata=thread_in.metadata
    )
    return thread


@app.post("/threads/{thread_id}/messages", response_model=schemas.MessageRead)
async def post_message(
    thread_id: UUID,
    message_in: schemas.MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    thread = await crud.get_thread_with_messages(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    msg = await crud.create_message(
        db,
        thread_id=thread_id,
        sender=message_in.sender,
        content=message_in.content,
        is_image=message_in.is_image,
        base64_image=message_in.base64_image,
        metadata=message_in.metadata,
    )
    return msg


@app.get("/threads/{thread_id}", response_model=schemas.ThreadRead)
async def load_thread(thread_id: UUID, db: AsyncSession = Depends(get_db)):
    thread = await crud.get_thread_with_messages(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
