"""Telegram message templates and inline keyboards for reminders and alerts."""

import uuid
from datetime import UTC, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from jobpilot.db.models import Event
from jobpilot.reminders.schedule_math import format_deadline_urgency, get_user_zone


def build_initial_event_keyboard(reminder_id: uuid.UUID) -> InlineKeyboardMarkup:
    """Build inline keyboard for new event: [🔁 Recur] [✖ Dismiss]."""
    keyboard = [
        [
            InlineKeyboardButton("🔁 Recur (10am & 7pm)", callback_data=f"recur:{reminder_id}"),
            InlineKeyboardButton("✖ Dismiss", callback_data=f"dismiss:{reminder_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def build_recurring_reminder_keyboard(
    reminder_id: uuid.UUID, link: str | None = None
) -> InlineKeyboardMarkup:
    """Build inline keyboard for recurring reminder: [✅ Mark done] [✖ Dismiss]."""
    buttons = []
    if link:
        buttons.append([InlineKeyboardButton("🔗 Open Assessment / Link", url=link)])

    buttons.append(
        [
            InlineKeyboardButton("✅ Mark Done", callback_data=f"done:{reminder_id}"),
            InlineKeyboardButton("✖ Dismiss", callback_data=f"dismiss:{reminder_id}"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def format_event_text(
    event: Event,
    now_utc: datetime | None = None,
    user_tz_name: str = "America/Chicago",
    is_recurring: bool = False,
) -> str:
    """Format full event notification markdown."""
    now = now_utc or datetime.now(UTC)
    user_tz = get_user_zone(user_tz_name)

    urgency = format_deadline_urgency(event.deadline_at, now)
    header_lines: list[str] = []

    if urgency:
        header_lines.append(f"{urgency}\n")

    kind_icon = "💻" if event.kind.lower() == "oa" else "🎙️"
    kind_title = "Online Assessment (OA)" if event.kind.lower() == "oa" else "Interview Invitation"

    if is_recurring:
        header_lines.append(f"⏰ **Reminder: {kind_title}**")
    else:
        header_lines.append(f"{kind_icon} **New {kind_title} Detected!**")

    lines = [
        *header_lines,
        f"🏢 **Company:** {event.company}",
    ]

    if event.role_title:
        lines.append(f"💼 **Role:** {event.role_title}")

    if event.platform:
        lines.append(f"🛠️ **Platform:** {event.platform}")

    if event.deadline_at:
        local_deadline = event.deadline_at.astimezone(user_tz)
        lines.append(f"⏳ **Deadline:** {local_deadline.strftime('%b %d, %Y at %I:%M %p %Z')}")

    if event.link:
        lines.append(f"🔗 **Link:** {event.link}")

    if not is_recurring:
        lines.append(
            "\n_Tap **Recur** to receive reminders twice a day (10:00 & 19:00) until finished._"
        )

    return "\n".join(lines)
