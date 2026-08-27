import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from rag.db.session import AsyncSessionLocal, worker_session


async def _select_one() -> int:
    async with worker_session() as session:
        result = await session.execute(text("SELECT 1"))
        return int(result.scalar())


async def _select_one_global() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        return int(result.scalar())


def _skip_if_unreachable(exc: BaseException) -> None:
    pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.mark.asyncio
async def test_worker_session_can_query():
    try:
        value = await _select_one()
    except (OSError, DBAPIError, ConnectionError) as e:
        _skip_if_unreachable(e)
    assert value == 1


def test_worker_session_works_across_separate_event_loops():
    def ping() -> int:
        return asyncio.run(_select_one())

    try:
        assert ping() == 1
        assert ping() == 1
    except (OSError, DBAPIError, ConnectionError) as e:
        _skip_if_unreachable(e)


def test_run_async_disposes_global_engine_between_tasks():
    """Celery uses asyncio.run() per task. Disposing the pooled engine before
    the loop closes avoids 'Future attached to a different loop'."""
    from rag.workers.celery_app import run_async

    try:
        assert run_async(_select_one_global()) == 1
        assert run_async(_select_one_global()) == 1
    except (OSError, DBAPIError, ConnectionError) as e:
        _skip_if_unreachable(e)
