from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from rag.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def worker_session() -> AsyncGenerator[AsyncSession, None]:
    """Session bound to the current event loop.

    Celery calls asyncio.run() per task, which closes the loop. A pooled
    engine from a previous loop raises "Future attached to a different loop".
    """
    task_engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await task_engine.dispose()
