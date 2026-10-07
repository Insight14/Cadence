"""Unit tests for ReminderScheduler tick engine."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Table
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jobpilot.db.models import Base, Event, Reminder, User
from jobpilot.reminders.scheduler import ReminderScheduler


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime has UTC tzinfo if SQLite stripped it."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@pytest.fixture
async def async_test_session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory SQLite async session for scheduler tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def init_tables(sync_conn: Connection) -> None:
        target_tables: list[Table] = [
            cast(Table, User.__table__),
            cast(Table, Event.__table__),
            cast(Table, Reminder.__table__),
        ]
        Base.metadata.create_all(bind=sync_conn, tables=target_tables)

    async with engine.begin() as conn:
        await conn.run_sync(init_tables)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_fires_due_reminder(async_test_session: AsyncSession) -> None:
    session = async_test_session

    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=12345,
        timezone="America/Chicago",
        paused=False,
    )
    session.add(user)
    await session.flush()

    event = Event(
        user_id=user.id,
        company="Google",
        role_title="Software Engineering Intern",
        kind="oa",
        status="pending",
        deadline_at=datetime.now(UTC) + timedelta(days=3),
    )
    session.add(event)
    await session.flush()

    # Reminder scheduled in the past (due now)
    past_fire = datetime.now(UTC) - timedelta(hours=1)
    reminder = Reminder(
        user_id=user.id,
        event_id=event.id,
        state="recurring",
        next_fire_at=past_fire,
        send_count=0,
    )
    session.add(reminder)
    await session.commit()

    mock_bot = MagicMock()
    mock_send = AsyncMock(return_value=999)

    scheduler = ReminderScheduler(bot=mock_bot)
    with patch("jobpilot.reminders.scheduler.send_telegram_alert", mock_send):
        fired = await scheduler.run_tick(session)

    assert fired == 1
    mock_send.assert_called_once()
    await session.refresh(reminder)
    assert reminder.send_count == 1
    assert reminder.telegram_message_id == 999
    assert reminder.next_fire_at is not None
    assert _ensure_utc(reminder.next_fire_at) > datetime.now(UTC)


@pytest.mark.asyncio
async def test_scheduler_skips_paused_user(async_test_session: AsyncSession) -> None:
    session = async_test_session

    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=12345,
        timezone="America/Chicago",
        paused=True,
    )
    session.add(user)
    await session.flush()

    event = Event(
        user_id=user.id,
        company="Amazon",
        kind="oa",
        status="pending",
    )
    session.add(event)
    await session.flush()

    reminder = Reminder(
        user_id=user.id,
        event_id=event.id,
        state="recurring",
        next_fire_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session.add(reminder)
    await session.commit()

    mock_send = AsyncMock()
    scheduler = ReminderScheduler()
    with patch("jobpilot.reminders.scheduler.send_telegram_alert", mock_send):
        fired = await scheduler.run_tick(session)

    assert fired == 0
    mock_send.assert_not_called()
    await session.refresh(reminder)
    assert reminder.next_fire_at is not None
    assert _ensure_utc(reminder.next_fire_at) > datetime.now(UTC)


@pytest.mark.asyncio
async def test_scheduler_expires_past_deadline(async_test_session: AsyncSession) -> None:
    session = async_test_session

    user = User(
        id=uuid.uuid4(),
        telegram_chat_id=12345,
        timezone="America/Chicago",
        paused=False,
    )
    session.add(user)
    await session.flush()

    event = Event(
        user_id=user.id,
        company="Apple",
        kind="oa",
        status="pending",
        deadline_at=datetime.now(UTC) - timedelta(hours=2),  # Deadline passed
    )
    session.add(event)
    await session.flush()

    reminder = Reminder(
        user_id=user.id,
        event_id=event.id,
        state="recurring",
        next_fire_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session.add(reminder)
    await session.commit()

    mock_send = AsyncMock()
    scheduler = ReminderScheduler()
    with patch("jobpilot.reminders.scheduler.send_telegram_alert", mock_send):
        fired = await scheduler.run_tick(session)

    assert fired == 0
    mock_send.assert_not_called()
    await session.refresh(event)
    await session.refresh(reminder)
    assert event.status == "expired"
    assert reminder.state == "done"
