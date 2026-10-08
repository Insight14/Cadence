"""Unit tests for Telegram bot /applications command and cold outreach callback actions."""

import datetime
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Table
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import Message, Update

from jobpilot.bot.handlers import applications_command, handle_callback_query
from jobpilot.db.models import (
    Application,
    Base,
    Company,
    Event,
    GmailAccount,
    JobPosting,
    Outreach,
    ProcessedEmail,
    Reminder,
    ResumeProfile,
    User,
    UserCompanyPref,
)


@pytest.fixture
async def app_db_factory() -> AsyncGenerator[
    tuple[async_sessionmaker[AsyncSession], Callable[[], Any]], None
]:
    """Create in-memory SQLite async engine and sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, User.__table__),
            cast(Table, GmailAccount.__table__),
            cast(Table, ProcessedEmail.__table__),
            cast(Table, Event.__table__),
            cast(Table, Reminder.__table__),
            cast(Table, Company.__table__),
            cast(Table, JobPosting.__table__),
            cast(Table, ResumeProfile.__table__),
            cast(Table, UserCompanyPref.__table__),
            cast(Table, Application.__table__),
            cast(Table, Outreach.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def get_session() -> AsyncSession:
        return session_maker()

    yield session_maker, get_session

    await engine.dispose()


@pytest.mark.asyncio
async def test_applications_command_empty(
    app_db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = app_db_factory
    chat_id = 12345

    async with await get_session() as db:
        user = User(id=uuid.uuid4(), email="user@test.com", telegram_chat_id=chat_id)
        db.add(user)
        await db.commit()

    update = MagicMock(spec=Update)
    update.effective_chat.id = chat_id
    update.message = AsyncMock(spec=Message)

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await applications_command(update, MagicMock())

    assert update.message.reply_text.called
    msg = update.message.reply_text.call_args[0][0]
    assert "No tracked job applications yet" in msg


@pytest.mark.asyncio
async def test_applications_command_with_records(
    app_db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = app_db_factory
    chat_id = 12345

    async with await get_session() as db:
        user = User(id=uuid.uuid4(), email="user@test.com", telegram_chat_id=chat_id)
        db.add(user)
        company = Company(
            id=uuid.uuid4(),
            name="Roblox",
            ats="lever",
            board_token="roblox",
            domains=["roblox.com"],
        )
        db.add(company)
        app = Application(
            id=uuid.uuid4(),
            user_id=user.id,
            company_id=company.id,
            status="applied",
            applied_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(app)
        outreach = Outreach(
            id=uuid.uuid4(),
            application_id=app.id,
            kind="cold_email_detected",
            contact_domain="roblox.com",
        )
        db.add(outreach)
        await db.commit()

    update = MagicMock(spec=Update)
    update.effective_chat.id = chat_id
    update.message = AsyncMock(spec=Message)

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await applications_command(update, MagicMock())

    assert update.message.reply_text.called
    msg = update.message.reply_text.call_args[0][0]
    assert "Your Tracked Applications (1)" in msg
    assert "Roblox" in msg
    assert "Cold Email Sent" in msg


@pytest.mark.asyncio
async def test_callback_draft_sent_snooze_actions(
    app_db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = app_db_factory
    chat_id = 12345
    app_id = uuid.uuid4()

    async with await get_session() as db:
        user = User(id=uuid.uuid4(), email="user@test.com", telegram_chat_id=chat_id)
        db.add(user)
        company = Company(
            id=uuid.uuid4(),
            name="Scale AI",
            ats="ashby",
            board_token="scaleai",
            domains=["scale.com"],
        )
        db.add(company)
        app = Application(
            id=app_id,
            user_id=user.id,
            company_id=company.id,
            status="applied",
            applied_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(app)
        prof = ResumeProfile(
            id=uuid.uuid4(),
            user_id=user.id,
            structured_json={
                "skills": ["Python", "PyTorch"],
                "target_roles": ["Machine Learning Engineer"],
                "domains": ["AI/ML"],
                "project_themes": ["LLM evaluation"],
                "summary": "AI researcher and engineer.",
            },
        )
        db.add(prof)
        await db.commit()

    # 1. Test draft action
    update_draft = MagicMock(spec=Update)
    update_draft.effective_chat.id = chat_id
    cb_draft = AsyncMock()
    cb_draft.data = f"draft:{app_id}"
    msg_draft = MagicMock(spec=Message)
    msg_draft.text = "Application Confirmed for Scale AI!"
    cb_draft.message = msg_draft
    update_draft.callback_query = cb_draft

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(update_draft, MagicMock())

    assert cb_draft.edit_message_text.called
    draft_msg = cb_draft.edit_message_text.call_args.kwargs["text"]
    assert "Cold Outreach Email Draft" in draft_msg

    # 2. Test sent action
    update_sent = MagicMock(spec=Update)
    update_sent.effective_chat.id = chat_id
    cb_sent = AsyncMock()
    cb_sent.data = f"sent:{app_id}"
    cb_sent.message = msg_draft
    update_sent.callback_query = cb_sent

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(update_sent, MagicMock())

    assert cb_sent.edit_message_text.called
    sent_msg = cb_sent.edit_message_text.call_args.kwargs["text"]
    assert "Marked as Sent!" in sent_msg

    # 3. Test snooze action
    update_snooze = MagicMock(spec=Update)
    update_snooze.effective_chat.id = chat_id
    cb_snooze = AsyncMock()
    cb_snooze.data = f"snooze:{app_id}"
    cb_snooze.message = msg_draft
    update_snooze.callback_query = cb_snooze

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(update_snooze, MagicMock())

    assert cb_snooze.edit_message_text.called
    snooze_msg = cb_snooze.edit_message_text.call_args.kwargs["text"]
    assert "Nudge snoozed" in snooze_msg
