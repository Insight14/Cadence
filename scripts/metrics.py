"""CLI metrics script reporting system-wide operational metrics."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select

from jobpilot.db.models import (
    Application,
    Company,
    Event,
    GmailAccount,
    JobAlert,
    JobPosting,
    Outreach,
    ProcessedEmail,
    Reminder,
    ResumeProfile,
    User,
    UserCompanyPref,
)
from jobpilot.db.session import async_session_factory


async def generate_metrics_report() -> None:
    """Query database and print formatted operational health and usage metrics."""
    async with await async_session_factory() as db:
        total_users = await db.scalar(select(func.count(User.id))) or 0
        linked_telegram = (
            await db.scalar(select(func.count(User.id)).where(User.telegram_chat_id.isnot(None)))
            or 0
        )
        connected_gmail = await db.scalar(select(func.count(GmailAccount.id))) or 0
        uploaded_resumes = await db.scalar(select(func.count(ResumeProfile.id))) or 0

        # Processed emails by classification label
        emails_stmt = select(ProcessedEmail.label, func.count(ProcessedEmail.id)).group_by(
            ProcessedEmail.label
        )
        email_counts = dict((await db.execute(emails_stmt)).all())
        total_emails = sum(email_counts.values())

        # Events & Reminders
        total_events = await db.scalar(select(func.count(Event.id))) or 0
        oa_events = (
            await db.scalar(select(func.count(Event.id)).where(Event.kind == "oa_deadline")) or 0
        )
        interview_events = (
            await db.scalar(
                select(func.count(Event.id)).where(Event.kind == "interview_invitation")
            )
            or 0
        )
        active_reminders = (
            await db.scalar(
                select(func.count(Reminder.id)).where(Reminder.state.in_(["pending", "recurring"]))
            )
            or 0
        )
        completed_reminders = (
            await db.scalar(select(func.count(Reminder.id)).where(Reminder.state == "done")) or 0
        )

        # Job Board Postings & Alerts
        total_companies = await db.scalar(select(func.count(Company.id))) or 0
        total_jobs = await db.scalar(select(func.count(JobPosting.id))) or 0
        open_jobs = (
            await db.scalar(select(func.count(JobPosting.id)).where(JobPosting.is_open.is_(True)))
            or 0
        )
        total_alerts = await db.scalar(select(func.count(JobAlert.id))) or 0
        muted_prefs = (
            await db.scalar(
                select(func.count(UserCompanyPref.id)).where(UserCompanyPref.status == "muted")
            )
            or 0
        )

        # Applications & Outreach
        total_apps = await db.scalar(select(func.count(Application.id))) or 0
        total_outreach = await db.scalar(select(func.count(Outreach.id))) or 0
        detected_outreach = (
            await db.scalar(
                select(func.count(Outreach.id)).where(Outreach.kind == "cold_email_detected")
            )
            or 0
        )
        nudges_dispatched = (
            await db.scalar(select(func.count(Outreach.id)).where(Outreach.kind == "nudge_sent"))
            or 0
        )

        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        print("=" * 65)
        print(f"       JobPilot Operational Metrics Report ({now_str})")
        print("=" * 65)
        print("👥 Users & Onboarding:")
        print(f"   • Total Candidates Registered:  {total_users}")
        print(f"   • Telegram Accounts Linked:    {linked_telegram}")
        print(f"   • Gmail Inboxes Connected:     {connected_gmail}")
        print(f"   • Structured Resumes Indexed:  {uploaded_resumes}")
        print()
        print("📨 Email Ingestion & Two-Stage Classifier:")
        print(f"   • Total Emails Processed:      {total_emails}")
        for label, count in sorted(email_counts.items()):
            print(f"     - {label:<26} {count}")
        print()
        print("⏰ Assessment & Interview Reminders:")
        print(f"   • Total Actionable Events:     {total_events}")
        print(f"     - OA Deadlines:              {oa_events}")
        print(f"     - Interview Invitations:     {interview_events}")
        print(f"   • Active Reminder Loops:       {active_reminders}")
        print(f"   • Successfully Completed:      {completed_reminders}")
        print()
        print("🎯 Career Boards & Vector Job Matching:")
        print(f"   • Monitored Companies:         {total_companies}")
        print(f"   • Total Indexed Postings:      {total_jobs} ({open_jobs} currently open)")
        print(f"   • Candidate Match Alerts:      {total_alerts}")
        print(f"   • Muted Company Prefs:         {muted_prefs}")
        print()
        print("🚀 Applications & Cold Outreach Tracker:")
        print(f"   • Tracked Applications:        {total_apps}")
        print(f"   • Total Outreach Events:       {total_outreach}")
        print(f"     - Prior Sent Email Detected: {detected_outreach}")
        print(f"     - Cold Outreach Nudges Sent: {nudges_dispatched}")
        print("=" * 65)


def main() -> None:
    asyncio.run(generate_metrics_report())


if __name__ == "__main__":
    main()
