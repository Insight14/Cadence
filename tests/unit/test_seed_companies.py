"""Unit tests for company catalog seeding."""

from collections.abc import AsyncGenerator
from typing import cast

import pytest
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.db.models import Base, Company
from jobpilot.jobs.seed import load_companies_yaml, seed_companies


@pytest.fixture
async def async_test_session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory SQLite async session for seed tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, Company.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


def test_load_companies_yaml() -> None:
    companies = load_companies_yaml()
    assert len(companies) >= 40

    names = {c["name"] for c in companies}
    assert "Waymo" in names
    assert "Uber" in names
    assert "Lyft" in names
    assert "Aurora" in names
    assert "Anthropic" in names
    assert "OpenAI" in names
    assert "Stripe" in names
    assert "Spotify" in names

    for c in companies:
        assert "name" in c
        assert "ats" in c
        assert c["ats"] in ("greenhouse", "lever", "ashby")
        assert "board_token" in c
        assert isinstance(c.get("domains"), list)
        assert isinstance(c.get("tags"), list)


@pytest.mark.asyncio
async def test_seed_companies_idempotency(async_test_session: AsyncSession) -> None:
    session = async_test_session

    # First run: should insert all companies
    inserted, updated = await seed_companies(session)
    assert inserted >= 40
    assert updated == 0

    stmt = select(Company)
    all_companies = list((await session.scalars(stmt)).all())
    assert len(all_companies) == inserted

    # Verify key properties
    waymo = next(c for c in all_companies if c.name == "Waymo")
    assert waymo.ats == "greenhouse"
    assert waymo.board_token == "waymo"
    assert "autonomy" in waymo.tags

    # Second run: should update without inserting duplicates
    inserted2, updated2 = await seed_companies(session)
    assert inserted2 == 0
    assert updated2 == len(all_companies)
