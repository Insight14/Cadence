"""Unit tests for JobBoardPoller diffing engine and change tracking."""

import uuid
from collections.abc import AsyncGenerator
from typing import cast

import httpx
import pytest
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.db.models import Base, Company, JobPosting
from jobpilot.jobs.poller import JobBoardPoller


@pytest.fixture
async def async_test_session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory SQLite async session for poller tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, Company.__table__),
            cast(Table, JobPosting.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_job_poller_diff_lifecycle(async_test_session: AsyncSession) -> None:
    session = async_test_session

    company = Company(
        id=uuid.uuid4(),
        name="Waymo",
        ats="greenhouse",
        board_token="waymo",
        domains=["waymo.com"],
        tags=["autonomy", "robotics"],
    )
    session.add(company)
    await session.commit()

    poller = JobBoardPoller()

    # --- Pass 1: Remote returns Job A (id: 101) and Job B (id: 102) ---
    pass1_payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Software Engineering Intern",
                "location": {"name": "Mountain View, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/101",
                "content": "Work on Waymo Driver.",
            },
            {
                "id": 102,
                "title": "Robotics Intern",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/102",
                "content": "Hardware and robotics testing.",
            },
        ]
    }

    def handler_pass1(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pass1_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_pass1)) as client:
        res1 = await poller.poll_company(session, company, client=client)

    assert res1.new_jobs_count == 2
    assert res1.updated_jobs_count == 0
    assert res1.closed_jobs_count == 0
    assert res1.total_open_count == 2

    # Verify rows in DB
    stmt = select(JobPosting).where(JobPosting.company_id == company.id)
    postings = list((await session.scalars(stmt)).all())
    assert len(postings) == 2
    assert all(p.is_open for p in postings)

    # --- Pass 2: Remote drops Job B (102), modifies Job A (101), and adds Job C (103) ---
    pass2_payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Software Engineering Intern (Summer 2026)",  # Title updated
                "location": {"name": "Mountain View, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/101",
                "content": "Work on Waymo Driver.",
            },
            {
                "id": 103,
                "title": "New Grad AI Research Engineer",  # New job
                "location": {"name": "New York, NY"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/103",
                "content": "Foundational ML.",
            },
        ]
    }

    def handler_pass2(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pass2_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_pass2)) as client:
        res2 = await poller.poll_company(session, company, client=client)

    assert res2.new_jobs_count == 1  # Job C added
    assert res2.updated_jobs_count == 1  # Job A updated
    assert res2.closed_jobs_count == 1  # Job B closed
    assert res2.total_open_count == 2  # Job A and Job C open

    # Verify DB states
    stmt_a = select(JobPosting).where(JobPosting.external_id == "101")
    job_a = await session.scalar(stmt_a)
    assert job_a is not None
    assert job_a.is_open is True
    assert job_a.title == "Software Engineering Intern (Summer 2026)"

    stmt_b = select(JobPosting).where(JobPosting.external_id == "102")
    job_b = await session.scalar(stmt_b)
    assert job_b is not None
    assert job_b.is_open is False  # Closed

    stmt_c = select(JobPosting).where(JobPosting.external_id == "103")
    job_c = await session.scalar(stmt_c)
    assert job_c is not None
    assert job_c.is_open is True

    # --- Pass 3: Job B (102) is reopened ---
    pass3_payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Software Engineering Intern (Summer 2026)",
                "location": {"name": "Mountain View, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/101",
            },
            {
                "id": 102,
                "title": "Robotics Intern",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/102",
            },
            {
                "id": 103,
                "title": "New Grad AI Research Engineer",
                "location": {"name": "New York, NY"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/103",
            },
        ]
    }

    def handler_pass3(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pass3_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_pass3)) as client:
        res3 = await poller.poll_company(session, company, client=client)

    assert res3.new_jobs_count == 0
    assert res3.updated_jobs_count == 1  # Job B reopened
    assert res3.closed_jobs_count == 0

    await session.refresh(job_b)
    assert job_b.is_open is True


@pytest.mark.asyncio
async def test_job_poller_304_not_modified(async_test_session: AsyncSession) -> None:
    session = async_test_session

    company = Company(
        id=uuid.uuid4(),
        name="Anthropic",
        ats="ashby",
        board_token="anthropic",
        domains=["anthropic.com"],
        tags=["ai"],
    )
    session.add(company)
    await session.commit()

    poller = JobBoardPoller()

    def handler_304(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_304)) as client:
        res = await poller.poll_company(session, company, client=client)

    assert res.new_jobs_count == 0
    assert res.updated_jobs_count == 0
    assert res.closed_jobs_count == 0
