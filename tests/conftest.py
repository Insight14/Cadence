"""Shared pytest fixtures for JobPilot unit tests."""

from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.db.models import Base


@pytest.fixture
async def db_factory() -> AsyncGenerator[
    tuple[async_sessionmaker[AsyncSession], Callable[[], Any]], None
]:
    """Create in-memory SQLite async engine and sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        Base.metadata.create_all(bind=sync_conn)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def get_session() -> AsyncSession:
        return session_maker()

    yield session_maker, get_session

    await engine.dispose()


@pytest.fixture
async def db_session(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> AsyncGenerator[AsyncSession, None]:
    """Create yielding AsyncSession from db_factory."""
    session_maker, _ = db_factory
    async with session_maker() as session:
        yield session
