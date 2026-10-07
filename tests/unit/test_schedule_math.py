"""Unit tests for pure scheduling math functions."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jobpilot.reminders.schedule_math import (
    calculate_next_fire_slot,
    format_deadline_urgency,
    get_user_zone,
    is_in_quiet_hours,
    validate_timezone,
)


def test_validate_timezone() -> None:
    assert validate_timezone("America/Chicago") is True
    assert validate_timezone("America/New_York") is True
    assert validate_timezone("Europe/London") is True
    assert validate_timezone("Asia/Kolkata") is True
    assert validate_timezone("Invalid/Timezone") is False
    assert validate_timezone("") is False


def test_get_user_zone_fallback() -> None:
    tz = get_user_zone("Invalid/Zone")
    assert tz.key == "America/Chicago"

    tz_valid = get_user_zone("America/Los_Angeles")
    assert tz_valid.key == "America/Los_Angeles"


def test_calculate_next_fire_slot_same_day() -> None:
    # 08:00 Central (14:00 UTC during CDT UTC-5) -> next slot is 10:00 Central (15:00 UTC)
    now_utc = datetime(2026, 6, 15, 13, 0, tzinfo=UTC)  # 08:00 CDT
    next_slot = calculate_next_fire_slot(now_utc, "America/Chicago")

    # Localized in Central time:
    central_slot = next_slot.astimezone(ZoneInfo("America/Chicago"))
    assert central_slot.year == 2026
    assert central_slot.month == 6
    assert central_slot.day == 15
    assert central_slot.hour == 10
    assert central_slot.minute == 0


def test_calculate_next_fire_slot_evening_same_day() -> None:
    # 12:00 Central (17:00 UTC) -> next slot is 19:00 Central (00:00 UTC next day)
    now_utc = datetime(2026, 6, 15, 17, 0, tzinfo=UTC)
    next_slot = calculate_next_fire_slot(now_utc, "America/Chicago")

    central_slot = next_slot.astimezone(ZoneInfo("America/Chicago"))
    assert central_slot.day == 15
    assert central_slot.hour == 19
    assert central_slot.minute == 0


def test_calculate_next_fire_slot_next_day_morning() -> None:
    # 20:00 Central (01:00 UTC next day) -> next slot is 10:00 Central next day
    now_utc = datetime(2026, 6, 15, 20, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
    next_slot = calculate_next_fire_slot(now_utc, "America/Chicago")

    central_slot = next_slot.astimezone(ZoneInfo("America/Chicago"))
    assert central_slot.day == 16
    assert central_slot.hour == 10
    assert central_slot.minute == 0


def test_calculate_next_fire_slot_dst_spring_forward() -> None:
    # US DST Spring Forward occurs on second Sunday of March (e.g., March 8, 2026)
    # Clock jumps from 02:00 to 03:00 local time (23-hour day)
    # Query at 01:00 AM on March 8, 2026 in America/New_York (EST, UTC-5)
    now_est = datetime(2026, 3, 8, 1, 0, tzinfo=ZoneInfo("America/New_York"))
    now_utc = now_est.astimezone(UTC)

    next_slot = calculate_next_fire_slot(now_utc, "America/New_York")
    ny_slot = next_slot.astimezone(ZoneInfo("America/New_York"))

    # Next slot should be 10:00 AM EDT (UTC-4)
    assert ny_slot.day == 8
    assert ny_slot.hour == 10
    assert ny_slot.minute == 0
    # In EDT, UTC offset is -4 hours, so 10:00 EDT == 14:00 UTC
    assert next_slot.hour == 14


def test_calculate_next_fire_slot_dst_fall_back() -> None:
    # US DST Fall Back occurs on first Sunday of Nov (e.g., Nov 1, 2026)
    # Clock falls back from 02:00 to 01:00 (25-hour day)
    # Query at 00:30 AM on Nov 1, 2026 in America/New_York (EDT, UTC-4)
    now_edt = datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo("America/New_York"))
    now_utc = now_edt.astimezone(UTC)

    next_slot = calculate_next_fire_slot(now_utc, "America/New_York")
    ny_slot = next_slot.astimezone(ZoneInfo("America/New_York"))

    # Next slot should be 10:00 AM EST (UTC-5)
    assert ny_slot.day == 1
    assert ny_slot.hour == 10
    assert ny_slot.minute == 0
    # In EST, UTC offset is -5 hours, so 10:00 EST == 15:00 UTC
    assert next_slot.hour == 15


def test_is_in_quiet_hours_none() -> None:
    now_utc = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert is_in_quiet_hours(now_utc, "America/Chicago", None, None) is False
    assert is_in_quiet_hours(now_utc, "America/Chicago", 22, None) is False


def test_is_in_quiet_hours_same_day_range() -> None:
    # Quiet hours: 13:00 to 15:00 (1 PM to 3 PM)
    # Local time 14:00 Central
    now_central = datetime(2026, 6, 15, 14, 0, tzinfo=ZoneInfo("America/Chicago"))
    now_utc = now_central.astimezone(UTC)
    assert is_in_quiet_hours(now_utc, "America/Chicago", 13, 15) is True

    # Local time 16:00 Central
    now_outside = datetime(2026, 6, 15, 16, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
    assert is_in_quiet_hours(now_outside, "America/Chicago", 13, 15) is False


def test_is_in_quiet_hours_overnight_range() -> None:
    # Quiet hours: 22:00 to 08:00 (10 PM to 8 AM next morning)
    # 23:00 Central -> True
    t1 = datetime(2026, 6, 15, 23, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
    assert is_in_quiet_hours(t1, "America/Chicago", 22, 8) is True

    # 03:00 Central -> True
    t2 = datetime(2026, 6, 16, 3, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
    assert is_in_quiet_hours(t2, "America/Chicago", 22, 8) is True

    # 10:00 Central -> False
    t3 = datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
    assert is_in_quiet_hours(t3, "America/Chicago", 22, 8) is False


def test_format_deadline_urgency() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    # None deadline
    assert format_deadline_urgency(None, now) is None

    # Passed deadline
    past = datetime(2026, 6, 15, 11, 0, tzinfo=UTC)
    res_past = format_deadline_urgency(past, now)
    assert res_past is not None and "Deadline has passed" in res_past

    # < 1 hour
    due_30m = datetime(2026, 6, 15, 12, 30, tzinfo=UTC)
    res_30m = format_deadline_urgency(due_30m, now)
    assert res_30m is not None and "30 minutes" in res_30m

    # < 24 hours
    due_5h = datetime(2026, 6, 15, 17, 0, tzinfo=UTC)
    res_5h = format_deadline_urgency(due_5h, now)
    assert res_5h is not None and "5 hours" in res_5h

    # < 48 hours
    due_36h = datetime(2026, 6, 16, 23, 0, tzinfo=UTC)
    res_36h = format_deadline_urgency(due_36h, now)
    assert res_36h is not None and "Due tomorrow" in res_36h

    # > 48 hours
    due_5d = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    res_5d = format_deadline_urgency(due_5d, now)
    assert res_5d is not None and "5 days" in res_5d
