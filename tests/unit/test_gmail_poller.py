"""Unit tests for GmailPoller incremental synchronization."""

import json
import uuid
from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.classify.llm_classifier import LLMClassifier
from jobpilot.db.models import Base, Event, GmailAccount, ProcessedEmail, Reminder, User
from jobpilot.gmail.poller import GmailPoller
from jobpilot.llm.client import FakeLLMClient


@pytest.fixture
async def in_memory_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an in-memory SQLite database session for testing poller persistence logic."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, User.__table__),
            cast(Table, GmailAccount.__table__),
            cast(Table, ProcessedEmail.__table__),
            cast(Table, Event.__table__),
            cast(Table, Reminder.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_poller_processes_oa_and_creates_event(
    in_memory_db_session: AsyncSession,
) -> None:
    """Test that a new OA email creates both ProcessedEmail and Event records."""
    session = in_memory_db_session

    # 1. Create test user and gmail account
    user = User(id=uuid.uuid4(), email="student@example.com")
    session.add(user)
    await session.flush()

    account = GmailAccount(
        user_id=user.id,
        google_email="student@example.com",
        refresh_token_encrypted="mock_encrypted_token",
        history_id="1000",
        status="active",
    )
    session.add(account)
    await session.commit()

    # 2. Mock Gmail API response
    mock_service = MagicMock()
    mock_service.users().messages().get().execute.side_effect = [
        # Metadata call
        {
            "id": "msg_oa_1",
            "threadId": "thr_1",
            "internalDate": "1760000000000",
            "snippet": "HackerRank assessment for Waymo",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Waymo <jobs@hackerrank.com>"},
                    {"name": "Subject", "value": "Waymo Software Engineering Coding Challenge"},
                ],
            },
        },
        # Full call
        {
            "id": "msg_oa_1",
            "threadId": "thr_1",
            "internalDate": "1760000000000",
            "snippet": "HackerRank assessment for Waymo",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Waymo <jobs@hackerrank.com>"},
                    {"name": "Subject", "value": "Waymo Software Engineering Coding Challenge"},
                ],
                "body": {"data": ""},
            },
        },
    ]

    canned_llm = {
        "label": "oa",
        "confidence": 0.98,
        "company": "Waymo",
        "role_title": "SWE Intern",
        "platform": "HackerRank",
        "deadline_iso": "2026-10-20T00:00:00+00:00",
        "link": "https://hackerrank.com/test/waymo",
    }
    fake_llm = FakeLLMClient(canned_responses=[json.dumps(canned_llm)])
    classifier = LLMClassifier(client=fake_llm)
    poller = GmailPoller(classifier=classifier)

    # 3. Process message
    processed = await poller._process_single_message(
        session=session,
        user_id=user.id,
        service=mock_service,
        gmail_message_id="msg_oa_1",
    )
    assert processed is True
    await session.commit()

    # 4. Verify DB records
    proc_stmt = select(ProcessedEmail).where(ProcessedEmail.user_id == user.id)
    proc_email = await session.scalar(proc_stmt)
    assert proc_email is not None
    assert proc_email.gmail_message_id == "msg_oa_1"
    assert proc_email.label == "oa"

    event_stmt = select(Event).where(Event.user_id == user.id)
    event = await session.scalar(event_stmt)
    assert event is not None
    assert event.company == "Waymo"
    assert event.platform == "HackerRank"
    assert event.kind == "oa"

    # 5. Test idempotency: re-processing same message_id should return False and not duplicate
    reprocessed = await poller._process_single_message(
        session=session,
        user_id=user.id,
        service=mock_service,
        gmail_message_id="msg_oa_1",
    )
    assert reprocessed is False


@pytest.mark.asyncio
async def test_poller_handles_invalid_grant(
    in_memory_db_session: AsyncSession,
) -> None:
    """Test that invalid_grant marks the Gmail account as needs_reauth."""
    session = in_memory_db_session
    user = User(id=uuid.uuid4(), email="student@example.com")
    session.add(user)
    await session.flush()

    account = GmailAccount(
        user_id=user.id,
        google_email="student@example.com",
        refresh_token_encrypted="invalid_token",
        history_id="1000",
        status="active",
    )
    session.add(account)
    await session.commit()

    poller = GmailPoller()

    with patch(
        "jobpilot.gmail.poller.build_gmail_service",
        side_effect=Exception("invalid_grant: Token has been expired or revoked."),
    ):
        count = await poller.poll_account(session, account)
        assert count == 0
        assert account.status == "needs_reauth"
