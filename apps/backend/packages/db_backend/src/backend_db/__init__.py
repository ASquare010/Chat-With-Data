from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from common.config.settings import settings

# echo=True while developing helps to debug SQL statements
engine = create_async_engine(
    settings.USER_DATABASE_URL, echo=settings.IS_DEV, future=True
)

# session factory for async sessions
AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """yield current SessionLocal"""
    async with AsyncSessionLocal() as session:
        yield session
