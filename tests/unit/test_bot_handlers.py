"""Unit tests for Telegram bot command handlers and callback query handlers."""

import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Table
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.bot.handlers import (
    delete_my_data_command,
    handle_callback_query,
    pause_command,
    resume_command,
    start_command,
    timezone_command,
)
from jobpilot.db.models import Base, Event, GmailAccount, ProcessedEmail, Reminder, User
from jobpilot.security.crypto import encrypt_token


@pytest.fixture
async def db_factory() -> AsyncGenerator[
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
async def test_start_command_unlinked(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    update = MagicMock()
    update.effective_chat.id = 123456
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await start_command(update, context)

    update.message.reply_text.assert_called_once()
    assert "Welcome to JobPilot" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_start_command_with_user_id(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            email="student@example.com",
            timezone="America/New_York",
            paused=False,
        )
        session.add(user)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 999888
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = [str(user_id)]

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await start_command(update, context)

    async with session_maker() as session:
        updated_user = await session.get(User, user_id)
        assert updated_user is not None
        assert updated_user.telegram_chat_id == 999888

    assert "Account linked successfully" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_timezone_command(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            telegram_chat_id=555444,
            timezone="America/Chicago",
            paused=False,
        )
        session.add(user)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 555444
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["America/Los_Angeles"]

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await timezone_command(update, context)

    async with session_maker() as session:
        updated_user = await session.get(User, user_id)
        assert updated_user is not None
        assert updated_user.timezone == "America/Los_Angeles"

    assert "Timezone updated" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_timezone_command_invalid(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    update = MagicMock()
    update.effective_chat.id = 555444
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["Invalid/Timezone_Name"]

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await timezone_command(update, context)

    assert "not a recognized IANA timezone" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_pause_and_resume_commands(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            telegram_chat_id=777,
            timezone="America/Chicago",
            paused=False,
        )
        session.add(user)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 777
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    # Pause
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await pause_command(update, context)

    async with session_maker() as session:
        user_paused = await session.get(User, user_id)
        assert user_paused is not None
        assert user_paused.paused is True

    # Resume
    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await resume_command(update, context)

    async with session_maker() as session:
        user_resumed = await session.get(User, user_id)
        assert user_resumed is not None
        assert user_resumed.paused is False


@pytest.mark.asyncio
async def test_delete_my_data_command(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            telegram_chat_id=888,
            timezone="America/Chicago",
            paused=False,
        )
        session.add(user)
        await session.flush()

        account = GmailAccount(
            user_id=user.id,
            google_email="test@example.com",
            refresh_token_encrypted=encrypt_token("fake-refresh-token"),
        )
        session.add(account)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 888
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    mock_post = AsyncMock()
    with (
        patch("jobpilot.bot.handlers.async_session_factory", get_session),
        patch("httpx.AsyncClient.post", mock_post),
    ):
        await delete_my_data_command(update, context)

    async with session_maker() as session:
        deleted_user = await session.get(User, user_id)
        assert deleted_user is None

    assert "permanently deleted" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_callback_query_recur(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    reminder_id = uuid.uuid4()

    async with session_maker() as session:
        user = User(
            id=user_id,
            telegram_chat_id=999,
            timezone="America/Chicago",
            paused=False,
        )
        session.add(user)
        await session.flush()

        event = Event(
            id=event_id,
            user_id=user.id,
            company="Stripe",
            role_title="SWE Intern",
            kind="oa",
            status="pending",
        )
        session.add(event)
        await session.flush()

        reminder = Reminder(
            id=reminder_id,
            user_id=user.id,
            event_id=event.id,
            state="awaiting_choice",
        )
        session.add(reminder)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 999
    query = MagicMock()
    query.data = f"recur:{reminder_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.text = "OA Alert"
    update.callback_query = query

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(update, MagicMock())

    async with session_maker() as session:
        updated_reminder = await session.get(Reminder, reminder_id)
        assert updated_reminder is not None
        assert updated_reminder.state == "recurring"
        assert updated_reminder.next_fire_at is not None

    assert "Recurring active" in query.edit_message_text.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_handle_callback_query_dismiss(
    db_factory: tuple[async_sessionmaker[AsyncSession], Callable[[], Any]],
) -> None:
    session_maker, get_session = db_factory

    user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    reminder_id = uuid.uuid4()

    async with session_maker() as session:
        user = User(id=user_id, telegram_chat_id=999, timezone="America/Chicago")
        session.add(user)
        await session.flush()

        event = Event(
            id=event_id,
            user_id=user.id,
            company="Meta",
            kind="interview",
            status="pending",
        )
        session.add(event)
        await session.flush()

        reminder = Reminder(
            id=reminder_id,
            user_id=user.id,
            event_id=event.id,
            state="awaiting_choice",
        )
        session.add(reminder)
        await session.commit()

    update = MagicMock()
    update.effective_chat.id = 999
    query = MagicMock()
    query.data = f"dismiss:{reminder_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.text = "Interview Alert"
    update.callback_query = query

    with patch("jobpilot.bot.handlers.async_session_factory", get_session):
        await handle_callback_query(update, MagicMock())

    async with session_maker() as session:
        updated_reminder = await session.get(Reminder, reminder_id)
        updated_event = await session.get(Event, event_id)
        assert updated_reminder is not None
        assert updated_event is not None
        assert updated_reminder.state == "dismissed"
        assert updated_event.status == "dismissed"
