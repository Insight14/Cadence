"""DB-driven reminder tick scheduler."""

import logging
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from jobpilot.bot.app import get_telegram_app, send_telegram_alert
from jobpilot.bot.messages import (
    build_recurring_reminder_keyboard,
    format_event_text,
)
from jobpilot.db.models import Event, Reminder, User
from jobpilot.reminders.schedule_math import (
    calculate_next_fire_slot,
    is_in_quiet_hours,
)

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Evaluates and dispatches scheduled recurring reminders using atomic DB locks."""

    def __init__(self, bot: Bot | None = None) -> None:
        self._bot = bot

    def _get_bot(self) -> Bot:
        if self._bot:
            return self._bot
        app = get_telegram_app()
        return cast(Bot, app.bot)

    async def run_tick(self, session: AsyncSession) -> int:
        """Execute one tick cycle across all pending recurring reminders.

        Uses SELECT ... FOR UPDATE SKIP LOCKED inside the active transaction.
        Returns the number of reminders successfully fired.
        """
        now = datetime.now(UTC)
        bot = self._get_bot()

        # Query recurring reminders due for firing with row-level locks
        stmt = (
            select(Reminder)
            .where(
                Reminder.state == "recurring",
                Reminder.next_fire_at.is_not(None),
                Reminder.next_fire_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        result = await session.scalars(stmt)
        due_reminders = list(result.all())

        if not due_reminders:
            return 0

        logger.info("Found %d recurring reminders due for firing", len(due_reminders))
        fired_count = 0

        for reminder in due_reminders:
            user = await session.get(User, reminder.user_id)
            event = await session.get(Event, reminder.event_id)

            if not user or not event:
                reminder.state = "dismissed"
                continue

            # Stop condition 1: User paused
            if user.paused:
                # Postpone without firing
                reminder.next_fire_at = calculate_next_fire_slot(now, user.timezone)
                continue

            # Stop condition 2: Event completed or dismissed
            if event.status in ("completed", "dismissed", "expired"):
                reminder.state = "done" if event.status == "completed" else "dismissed"
                continue

            # Stop condition 3: Deadline expired
            if event.deadline_at and event.deadline_at <= now:
                logger.info("Deadline expired for event %s. Marking expired.", event.id)
                event.status = "expired"
                reminder.state = "done"
                continue

            # Check quiet hours: if in quiet hours, push to next slot
            if is_in_quiet_hours(
                now_utc=now,
                user_tz_name=user.timezone,
                quiet_start=user.quiet_hours_start,
                quiet_end=user.quiet_hours_end,
            ):
                logger.debug(
                    "User %s is in quiet hours. Deferring reminder %s.",
                    user.id,
                    reminder.id,
                )
                reminder.next_fire_at = calculate_next_fire_slot(now, user.timezone)
                continue

            # Check Telegram linking
            if not user.telegram_chat_id:
                logger.debug("User %s has no linked Telegram chat ID. Deferring.", user.id)
                reminder.next_fire_at = calculate_next_fire_slot(now, user.timezone)
                continue

            # Format reminder message
            message_text = format_event_text(
                event=event,
                now_utc=now,
                user_tz_name=user.timezone,
                is_recurring=True,
            )
            keyboard = build_recurring_reminder_keyboard(
                reminder_id=reminder.id,
                link=event.link,
            )

            # Send Telegram alert
            msg_id = await send_telegram_alert(
                bot=bot,
                chat_id=user.telegram_chat_id,
                text=message_text,
                reply_markup=keyboard,
            )

            if msg_id is None:
                # Handle error (bot blocked or chat not found) -> pause user
                logger.warning(
                    "Failed to send message to user %s. Pausing user reminders.",
                    user.id,
                )
                user.paused = True
            else:
                reminder.telegram_message_id = msg_id
                reminder.last_sent_at = now
                reminder.send_count += 1
                fired_count += 1

            # Advance next_fire_at to the next 10am/7pm slot
            reminder.next_fire_at = calculate_next_fire_slot(now, user.timezone)

        await session.commit()
        return fired_count
