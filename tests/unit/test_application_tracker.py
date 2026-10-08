"""Unit tests for ApplicationTracker and LinkedIn search link builder."""

import datetime
import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.applications.nudge import (
    build_linkedin_hiring_manager_search_url,
    build_linkedin_recruiter_search_url,
)
from jobpilot.applications.tracker import ApplicationTracker
from jobpilot.db.models import (
    Application,
    Base,
    Company,
    Outreach,
    ProcessedEmail,
    User,
)


@pytest.fixture
async def db_session_maker() -> async_sessionmaker[AsyncSession]:
    """Create in-memory SQLite async engine and sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, User.__table__),
            cast(Table, Company.__table__),
            cast(Table, ProcessedEmail.__table__),
            cast(Table, Application.__table__),
            cast(Table, Outreach.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return session_maker


def test_linkedin_url_builders() -> None:
    recruiter_url = build_linkedin_recruiter_search_url("Google")
    assert "linkedin.com/search/results/people" in recruiter_url
    assert "Google" in recruiter_url
    assert "recruiter" in recruiter_url.lower()

    manager_url = build_linkedin_hiring_manager_search_url("Stripe", "Software Engineer")
    assert "linkedin.com/search/results/people" in manager_url
    assert "Stripe" in manager_url
    assert "manager" in manager_url.lower()


@pytest.mark.asyncio
async def test_process_confirmation_with_prior_sent_outreach(
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_maker() as session:
        user = User(id=uuid.uuid4(), email="student@utdallas.edu", telegram_chat_id=12345)
        session.add(user)
        company = Company(
            id=uuid.uuid4(),
            name="Datadog",
            ats="greenhouse",
            board_token="datadog",
            domains=["datadog.com", "datadoghq.com"],
            tags=["cloud"],
        )
        session.add(company)
        proc_email = ProcessedEmail(
            id=uuid.uuid4(),
            user_id=user.id,
            gmail_message_id="msg_app_1",
            sender_domain="datadoghq.com",
            label="application_confirmation",
            received_at=datetime.datetime.now(datetime.UTC),
        )
        session.add(proc_email)
        await session.commit()

        # Mock Gmail service returning prior sent email
        mock_gmail = MagicMock()
        messages_mock = MagicMock()
        mock_gmail.users.return_value.messages.return_value = messages_mock
        messages_mock.list.return_value.execute.return_value = {"messages": [{"id": "sent_1"}]}

        mock_bot = AsyncMock()
        tracker = ApplicationTracker()

        app = await tracker.process_confirmation_email(
            session=session,
            user_id=user.id,
            proc_email=proc_email,
            company_name="Datadog",
            role_title="Software Engineer Intern",
            gmail_service=mock_gmail,
            bot=mock_bot,
        )

        assert app is not None
        assert app.status == "applied"

        # Check Outreach record
        stmt_outreach = select(Outreach).where(Outreach.application_id == app.id)
        outreaches = list((await session.scalars(stmt_outreach)).all())
        assert len(outreaches) == 1
        assert outreaches[0].kind == "cold_email_detected"

        # Telegram nudge should NOT have been sent because outreach already existed
        assert mock_bot.send_message.called is False


@pytest.mark.asyncio
async def test_process_confirmation_without_prior_outreach_sends_nudge(
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_maker() as session:
        user = User(id=uuid.uuid4(), email="student@utdallas.edu", telegram_chat_id=999888)
        session.add(user)
        proc_email = ProcessedEmail(
            id=uuid.uuid4(),
            user_id=user.id,
            gmail_message_id="msg_app_2",
            sender_domain="ramp.com",
            label="application_confirmation",
            received_at=datetime.datetime.now(datetime.UTC),
        )
        session.add(proc_email)
        await session.commit()

        # Mock Gmail service returning NO sent emails
        mock_gmail = MagicMock()
        messages_mock = MagicMock()
        mock_gmail.users.return_value.messages.return_value = messages_mock
        messages_mock.list.return_value.execute.return_value = {"messages": []}

        mock_bot = AsyncMock()
        tracker = ApplicationTracker()

        app = await tracker.process_confirmation_email(
            session=session,
            user_id=user.id,
            proc_email=proc_email,
            company_name="Ramp",
            role_title="Frontend Engineer Intern",
            gmail_service=mock_gmail,
            bot=mock_bot,
        )

        assert app is not None

        # Check Outreach record
        stmt_outreach = select(Outreach).where(Outreach.application_id == app.id)
        outreaches = list((await session.scalars(stmt_outreach)).all())
        assert len(outreaches) == 1
        assert outreaches[0].kind == "nudge_sent"

        # Telegram nudge should have been sent
        assert mock_bot.send_message.called is True
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 999888
        assert "Application Confirmed for Ramp" in call_kwargs["text"]
        assert call_kwargs["reply_markup"] is not None
