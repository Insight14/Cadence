"""SQLAlchemy 2.0 async declarative models."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class StringArray(TypeDecorator[list[str]]):
    """PostgreSQL ARRAY(String) with SQLite JSON fallback for testing."""

    impl = ARRAY(String)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[str] | None, dialect: Any) -> Any:
        return value

    def process_result_value(self, value: Any, dialect: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return list(value)


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    """Render pgvector Vector as BLOB for SQLite testing support."""
    return "BLOB"


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class User(Base, TimestampMixin):
    """User entity."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
        index=True,
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="America/Chicago",
        nullable=False,
    )
    quiet_hours_start: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Hour of day (0-23) in user timezone when quiet hours begin",
    )
    quiet_hours_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Hour of day (0-23) in user timezone when quiet hours end",
    )
    paused: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Relationships
    gmail_accounts: Mapped[list["GmailAccount"]] = relationship(
        "GmailAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    processed_emails: Mapped[list["ProcessedEmail"]] = relationship(
        "ProcessedEmail",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    company_prefs: Mapped[list["UserCompanyPref"]] = relationship(
        "UserCompanyPref",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    resume_profile: Mapped["ResumeProfile | None"] = relationship(
        "ResumeProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    job_alerts: Mapped[list["JobAlert"]] = relationship(
        "JobAlert",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class GmailAccount(Base, TimestampMixin):
    """Connected Gmail account for read-only sync."""

    __tablename__ = "gmail_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    google_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    refresh_token_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    history_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="active | needs_reauth | disabled",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="gmail_accounts")


class ProcessedEmail(Base, TimestampMixin):
    """Metadata-only record of processed emails (privacy-minimal)."""

    __tablename__ = "processed_emails"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_message_id", name="uq_user_gmail_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gmail_message_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    sender_domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="oa | interview | application_confirmation | rejection | other",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="processed_emails")
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="processed_email",
        cascade="all, delete-orphan",
    )


class Event(Base, TimestampMixin):
    """Detected OA or interview invitation event."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    processed_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processed_emails.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="oa | interview",
    )
    company: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role_title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    platform: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc="HackerRank, CodeSignal, HireVue, Karat, etc.",
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    link: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="active | completed | expired | dismissed",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="events")
    processed_email: Mapped["ProcessedEmail | None"] = relationship(
        "ProcessedEmail",
        back_populates="events",
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class Reminder(Base, TimestampMixin):
    """Interactive reminder scheduled in the DB-driven tick engine."""

    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_state_next_fire", "state", "next_fire_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(
        String(32),
        default="awaiting_choice",
        nullable=False,
        doc="awaiting_choice | recurring | dismissed | done",
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    send_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="reminders")
    user: Mapped["User"] = relationship("User", back_populates="reminders")


class Company(Base, TimestampMixin):
    """Monitored employer and career board configuration."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    ats: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="greenhouse | lever | ashby | workday | other",
    )
    board_token: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    domains: Mapped[list[str]] = mapped_column(
        StringArray,
        default=list,
        nullable=False,
    )
    tags: Mapped[list[str]] = mapped_column(
        StringArray,
        default=list,
        nullable=False,
    )
    careers_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    job_postings: Mapped[list["JobPosting"]] = relationship(
        "JobPosting",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    user_prefs: Mapped[list["UserCompanyPref"]] = relationship(
        "UserCompanyPref",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="company",
    )


class UserCompanyPref(Base, TimestampMixin):
    """User watch/mute preference for a company."""

    __tablename__ = "user_company_prefs"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company_pref"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="watch",
        nullable=False,
        doc="watch | muted",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="company_prefs")
    company: Mapped["Company"] = relationship("Company", back_populates="user_prefs")


class JobPosting(Base, TimestampMixin):
    """Tracked job posting scraped from career board."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("company_id", "external_id", name="uq_company_job_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    description_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    embedding: Mapped[Any | None] = mapped_column(
        Vector(1536),
        nullable=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    is_open: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="job_postings")
    alerts: Mapped[list["JobAlert"]] = relationship(
        "JobAlert",
        back_populates="job_posting",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="job_posting",
    )


class ResumeProfile(Base, TimestampMixin):
    """Structured resume profile extracted by LLM with embedding vector."""

    __tablename__ = "resume_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    structured_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    embedding: Mapped[Any | None] = mapped_column(
        Vector(1536),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="resume_profile")


class JobAlert(Base, TimestampMixin):
    """Record of sent job alerts to prevent duplicate notifications."""

    __tablename__ = "job_alerts"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_user_job_alert"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="job_alerts")
    job_posting: Mapped["JobPosting"] = relationship("JobPosting", back_populates="alerts")


class Application(Base, TimestampMixin):
    """Tracked user job application."""

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_postings.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="applied",
        nullable=False,
        doc="applied | oa | interview | offer | rejected",
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    confirmation_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processed_emails.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="applications")
    company: Mapped["Company"] = relationship("Company", back_populates="applications")
    job_posting: Mapped["JobPosting | None"] = relationship(
        "JobPosting",
        back_populates="applications",
    )
    confirmation_email: Mapped["ProcessedEmail | None"] = relationship("ProcessedEmail")
    outreach_records: Mapped[list["Outreach"]] = relationship(
        "Outreach",
        back_populates="application",
        cascade="all, delete-orphan",
    )


class Outreach(Base, TimestampMixin):
    """Cold outreach detection and nudges for an application."""

    __tablename__ = "outreach"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="cold_email_detected | nudge_sent | draft_generated",
    )
    contact_domain: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Relationships
    application: Mapped["Application"] = relationship(
        "Application",
        back_populates="outreach_records",
    )
