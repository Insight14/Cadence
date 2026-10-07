"""Unit tests verifying SQLAlchemy models and table metadata."""

from jobpilot.db.models import (
    Base,
    Company,
    User,
)


def test_all_tables_registered_in_metadata() -> None:
    """Verify that all required tables from Project Spec Section 4 are present."""
    expected_tables = {
        "users",
        "gmail_accounts",
        "processed_emails",
        "events",
        "reminders",
        "companies",
        "user_company_prefs",
        "job_postings",
        "resume_profiles",
        "job_alerts",
        "applications",
        "outreach",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables)


def test_table_columns_and_constraints() -> None:
    """Verify specific required columns and unique constraints on key tables."""
    tables = Base.metadata.tables

    # users
    users_table = tables["users"]
    assert "telegram_chat_id" in users_table.c
    assert "timezone" in users_table.c
    assert "quiet_hours_start" in users_table.c
    assert "quiet_hours_end" in users_table.c

    # processed_emails: no body or subject columns allowed (privacy-minimal)
    processed_emails = tables["processed_emails"]
    assert "subject" not in processed_emails.c
    assert "body" not in processed_emails.c
    assert "body_snippet" not in processed_emails.c
    assert "gmail_message_id" in processed_emails.c
    assert "label" in processed_emails.c

    # reminders
    reminders = tables["reminders"]
    assert "state" in reminders.c
    assert "next_fire_at" in reminders.c

    # job_postings: vector embedding column exists
    job_postings = tables["job_postings"]
    assert "embedding" in job_postings.c
    assert "external_id" in job_postings.c

    # resume_profiles: jsonb and vector embedding column exists
    resume_profiles = tables["resume_profiles"]
    assert "structured_json" in resume_profiles.c
    assert "embedding" in resume_profiles.c


def test_model_instantiation() -> None:
    """Verify model instances can be created in memory."""
    user = User(
        timezone="America/New_York",
        paused=False,
    )
    assert user.timezone == "America/New_York"
    assert not user.paused

    company = Company(
        name="Waymo",
        ats="greenhouse",
        board_token="waymo",
        domains=["waymo.com"],
        tags=["autonomy", "robotics"],
    )
    assert company.name == "Waymo"
    assert "autonomy" in company.tags
