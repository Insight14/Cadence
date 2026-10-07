"""Pure scheduling math functions for computing reminder slots and deadline urgency."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_timezone(tz_name: str) -> bool:
    """Check if an IANA timezone string is valid."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def get_user_zone(tz_name: str) -> ZoneInfo:
    """Return ZoneInfo for tz_name or fallback to America/Chicago."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/Chicago")


def calculate_next_fire_slot(
    now_utc: datetime,
    user_tz_name: str,
    target_hours: tuple[int, ...] = (10, 19),
) -> datetime:
    """Compute the next scheduled reminder slot (10:00 or 19:00) in user's local timezone.

    Returns timezone-aware UTC datetime.
    Pure function with full DST spring-forward & fall-back safety.
    """
    user_tz = get_user_zone(user_tz_name)
    user_now = now_utc.astimezone(user_tz)

    today = user_now.date()
    candidates: list[datetime] = []

    # Check slots today and next 2 days to account for DST shifts
    for day_offset in range(3):
        current_date = today + timedelta(days=day_offset)
        for hour in target_hours:
            # Construct naive time and localize to properly apply fold/DST offset
            slot_local = datetime(
                year=current_date.year,
                month=current_date.month,
                day=current_date.day,
                hour=hour,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=user_tz,
            )
            if slot_local > user_now:
                candidates.append(slot_local)

    if not candidates:
        # Fallback 12 hours from now in case of empty candidates
        return now_utc + timedelta(hours=12)

    earliest_local = min(candidates)
    return earliest_local.astimezone(UTC)


def is_in_quiet_hours(
    now_utc: datetime,
    user_tz_name: str,
    quiet_start: int | None,
    quiet_end: int | None,
) -> bool:
    """Check if current time falls within user's configured quiet hours."""
    if quiet_start is None or quiet_end is None:
        return False

    user_tz = get_user_zone(user_tz_name)
    user_now = now_utc.astimezone(user_tz)
    current_hour = user_now.hour

    if quiet_start <= quiet_end:
        # E.g. 22 to 23
        return quiet_start <= current_hour < quiet_end
    else:
        # Crosses midnight: E.g. 22:00 to 08:00
        return current_hour >= quiet_start or current_hour < quiet_end


def format_deadline_urgency(
    deadline_utc: datetime | None,
    now_utc: datetime,
) -> str | None:
    """Generate urgency alert string if deadline is approaching.

    Returns bold alert header when <= 24 hours remain.
    """
    if not deadline_utc:
        return None

    diff = deadline_utc - now_utc
    total_seconds = diff.total_seconds()

    if total_seconds <= 0:
        return "⚠️ **Deadline has passed**"

    hours_remaining = total_seconds / 3600.0
    if hours_remaining <= 1.0:
        minutes = max(1, int(total_seconds / 60.0))
        return f"🚨 **Due in {minutes} minutes!**"
    elif hours_remaining <= 24.0:
        hours = int(hours_remaining)
        return f"🚨 **Due in {hours} hours!**"
    elif hours_remaining <= 48.0:
        return "⏰ **Due tomorrow!**"
    else:
        days = int(hours_remaining / 24.0)
        return f"📅 **Due in {days} days**"
