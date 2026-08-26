import asyncio

import pytest
from sqlalchemy import text

from rag.db.session import worker_session


@pytest.mark.asyncio
async def test_worker_session_can_query():
    async with worker_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_worker_session_works_across_separate_event_loops():
    async def ping() -> int:
        async with worker_session() as session:
            result = await session.execute(text("SELECT 1"))
            return int(result.scalar())

    assert asyncio.run(ping()) == 1
    assert asyncio.run(ping()) == 1
