import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://asquare:bro_secret@localhost:5431/chat_with_data_db",
)

# echo=True while developing helps to debug SQL statements
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# session factory for async sessions
AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
