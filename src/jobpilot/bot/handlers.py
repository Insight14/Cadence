"""Telegram bot command handlers and interactive callback query dispatchers."""

import datetime
import logging
import uuid

import httpx
from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from jobpilot.applications.drafter import ColdEmailDrafter
from jobpilot.db.models import (
    Application,
    Company,
    Event,
    GmailAccount,
    JobAlert,
    JobPosting,
    Outreach,
    Reminder,
    ResumeProfile,
    User,
    UserCompanyPref,
)
from jobpilot.db.session import async_session_factory
from jobpilot.jobs.matcher import JobMatcher
from jobpilot.reminders.schedule_math import (
    calculate_next_fire_slot,
    get_user_zone,
    validate_timezone,
)
from jobpilot.resume.extractor import StructuredResumeProfile
from jobpilot.security.crypto import decrypt_token

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command, optionally with a linking token."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []

    async with await async_session_factory() as db:
        # Check if already linked
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)

        if args:
            token = args[0].strip()
            # Attempt to link user by user UUID or token
            linked_user = None
            try:
                user_id = uuid.UUID(token)
                linked_user = await db.get(User, user_id)
            except ValueError:
                pass

            if not linked_user:
                # Try finding by email
                stmt_email = select(User).where(User.email == token)
                linked_user = await db.scalar(stmt_email)

            if linked_user:
                linked_user.telegram_chat_id = chat_id
                await db.commit()
                await update.message.reply_text(
                    f"✅ **Account linked successfully!**\n\n"
                    f"👤 **Email:** `{linked_user.email or 'Connected'}`\n"
                    f"🕒 **Timezone:** `{linked_user.timezone}`\n"
                    f"(change with `/timezone <IANA>`)\n\n"
                    f"You will now receive instant notifications when new Online Assessments, "
                    f"job matches, and application nudges drop!",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

        if user:
            await update.message.reply_text(
                f"👋 **Welcome back to JobPilot!**\n\n"
                f"Your Telegram is linked to `{user.email or 'your account'}`.\n"
                f"🕒 Current timezone: `{user.timezone}`\n\n"
                f"**Available Commands:**\n"
                f"• `/matches` — View your top matching open jobs right now\n"
                f"• `/applications` — Track all active job applications & outreach\n"
                f"• `/lead <url>` — Submit a manual job lead link to track\n"
                f"• `/threshold <score>` — Set minimum match score (e.g. `0.50`)\n"
                f"• `/stats` — View your personal application & reminder stats\n"
                f"• `/mute <company>` — Mute job alerts for a specific company\n"
                f"• `/unmute <company>` — Unmute job alerts for a company\n"
                f"• `/timezone <IANA>` — Update your timezone (e.g. `America/New_York`)\n"
                f"• `/pause` — Temporarily pause reminder notifications\n"
                f"• `/resume` — Resume reminders\n"
                f"• `/delete_my_data` — Wipe all your data and revoke Google permissions",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "👋 **Welcome to JobPilot!**\n\n"
                "To link your Telegram account to JobPilot:\n"
                "1. Connect Gmail & upload resume at `http://localhost:8000`\n"
                "2. Send `/link <your_user_id_or_email>` here in chat.\n\n"
                "Once linked, you'll receive interactive reminders and match alerts!",
                parse_mode=ParseMode.MARKDOWN,
            )


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /link <token_or_email> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/link <user_id_or_email>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    token = args[0].strip()
    async with await async_session_factory() as db:
        user = None
        try:
            user_id = uuid.UUID(token)
            user = await db.get(User, user_id)
        except ValueError:
            pass

        if not user:
            stmt = select(User).where(User.email == token)
            user = await db.scalar(stmt)

        if not user:
            await update.message.reply_text(
                "❌ No user found matching that ID or email. Please check and try again."
            )
            return

        user.telegram_chat_id = chat_id
        await db.commit()
        await update.message.reply_text(
            f"✅ **Telegram linked successfully!**\n\n"
            f"👤 **Account:** `{user.email or user.id}`\n"
            f"🕒 **Timezone:** `{user.timezone}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def matches_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /matches command: fetch top matching job postings for the candidate."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked. Use `/link <user_id>` first.")
            return

        prof = await db.scalar(select(ResumeProfile).where(ResumeProfile.user_id == user.id))
        if not prof:
            await update.message.reply_text(
                "📄 **No resume profile found yet!**\n\n"
                "Please upload your resume at `http://localhost:8000` to extract your skills "
                "and start receiving job matches.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        matcher = JobMatcher()
        matches = await matcher.find_matches_for_user(db, user.id, min_score=0.40, max_matches=5)

        if not matches:
            await update.message.reply_text(
                "🔍 **No open matches right now.**\n\n"
                "JobPilot is polling target career boards continuously. "
                "You'll receive alerts the moment matching roles drop!",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        response_lines = ["🎯 **Top Open Job Matches For You:**\n"]
        for idx, m in enumerate(matches, 1):
            score_pct = int(m.similarity_score * 100)
            response_lines.append(
                f"**{idx}. [{m.job.title}]({m.job.url})**\n"
                f"🏢 **Company:** {m.company.name}\n"
                f"📍 **Location:** {m.job.location or 'Not specified'}\n"
                f"📊 **Affinity:** {score_pct}%\n"
                f"💡 _{m.why_matched or 'Relevant match based on your skills'}_\n"
            )

        await update.message.reply_text(
            "\n".join(response_lines),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mute <company_name> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/mute <Company Name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_name = " ".join(args).strip()
    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        # Find company
        stmt_comp = select(Company).where(Company.name.ilike(f"%{target_name}%"))
        company = await db.scalar(stmt_comp)
        if not company:
            await update.message.reply_text(f"❌ Could not find company matching '{target_name}'.")
            return

        # Upsert preference
        pref_stmt = select(UserCompanyPref).where(
            UserCompanyPref.user_id == user.id,
            UserCompanyPref.company_id == company.id,
        )
        pref = await db.scalar(pref_stmt)
        if pref:
            pref.status = "muted"
        else:
            pref = UserCompanyPref(user_id=user.id, company_id=company.id, status="muted")
            db.add(pref)

        await db.commit()
        await update.message.reply_text(
            f"🔕 **Muted {company.name}.**\n"
            f"You will no longer receive alerts for this company. "
            f"Use `/unmute {company.name}` to re-enable.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unmute <company_name> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/unmute <Company Name>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_name = " ".join(args).strip()
    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        stmt_comp = select(Company).where(Company.name.ilike(f"%{target_name}%"))
        company = await db.scalar(stmt_comp)
        if not company:
            await update.message.reply_text(f"❌ Could not find company matching '{target_name}'.")
            return

        pref_stmt = select(UserCompanyPref).where(
            UserCompanyPref.user_id == user.id,
            UserCompanyPref.company_id == company.id,
        )
        pref = await db.scalar(pref_stmt)
        if pref:
            pref.status = "watch"
            await db.commit()

        await update.message.reply_text(
            f"🔔 **Unmuted {company.name}!**\n"
            f"You will receive alerts when new matching roles open at this company.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def lead_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /lead <url> command: manually track a job lead pasted by candidate."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/lead <job_url>`\n"
            "Example: `/lead https://boards.greenhouse.io/stripe/jobs/12345`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    job_url = args[0].strip()
    if not job_url.startswith("http://") and not job_url.startswith("https://"):
        await update.message.reply_text(
            "❌ Please provide a valid URL starting with http:// or https://"
        )
        return

    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked. Use `/link <user_id>` first.")
            return

        import urllib.parse

        parsed = urllib.parse.urlparse(job_url)
        domain = parsed.netloc.lower().removeprefix("www.")
        path_parts = [p for p in parsed.path.split("/") if p]

        if "greenhouse.io" in domain and path_parts:
            comp_name = path_parts[0].capitalize()
        elif "lever.co" in domain and path_parts:
            comp_name = path_parts[0].capitalize()
        elif "ashbyhq.com" in domain and path_parts:
            comp_name = path_parts[0].capitalize()
        elif domain:
            comp_name = domain.split(".")[0].capitalize()
        else:
            comp_name = "Company Lead"

        stmt = select(Company).where(Company.name.ilike(comp_name))
        company = await db.scalar(stmt)
        if not company:
            company = Company(
                name=comp_name,
                ats="other",
                board_token=comp_name.lower().replace(" ", "-"),
                domains=[domain],
                tags=[],
            )
            db.add(company)
            await db.flush()

        stmt_job = select(JobPosting).where(JobPosting.url == job_url)
        job = await db.scalar(stmt_job)
        if not job:
            job = JobPosting(
                company_id=company.id,
                external_id=f"lead_{uuid.uuid4().hex[:12]}",
                title=f"{comp_name} Role (Manual Lead)",
                url=job_url,
                location="Direct Submission",
                is_open=True,
            )
            db.add(job)
            await db.flush()

        stmt_app = select(Application).where(
            Application.user_id == user.id,
            Application.company_id == company.id,
        )
        app = await db.scalar(stmt_app)
        if not app:
            app = Application(
                user_id=user.id,
                company_id=company.id,
                job_posting_id=job.id,
                status="applied",
                applied_at=datetime.datetime.now(datetime.UTC),
            )
            db.add(app)
            await db.flush()

        await db.commit()

        await update.message.reply_text(
            f"📌 **Job Lead Tracked!**\n\n"
            f"🏢 **Company:** {company.name}\n"
            f"🔗 **URL:** [{job_url}]({job_url})\n\n"
            f"Track and generate cold outreach anytime using `/applications`.",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


async def threshold_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /threshold <0.0 - 1.0> command: customize minimum match score threshold."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/threshold <score>` (e.g. `/threshold 0.50`)\n"
            "Sets your minimum affinity threshold for job match alerts.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        val = float(args[0].strip())
        if not (0.0 <= val <= 1.0):
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Please provide a score between 0.0 and 1.0 (e.g. `0.50`)."
        )
        return

    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        prof = await db.scalar(select(ResumeProfile).where(ResumeProfile.user_id == user.id))
        if prof and prof.structured_json:
            prof.structured_json["min_score_threshold"] = val
            await db.commit()

        await update.message.reply_text(
            f"🎯 **Match threshold updated to {int(val * 100)}%!**\n"
            f"You will receive alerts for jobs with at least {int(val * 100)}% skill affinity.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command: candidate personalized activity summary."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        app_count = (
            await db.scalar(
                select(func.count(Application.id)).where(Application.user_id == user.id)
            )
            or 0
        )
        rem_count = (
            await db.scalar(
                select(func.count(Reminder.id)).where(
                    Reminder.user_id == user.id,
                    Reminder.state.in_(["pending", "recurring"]),
                )
            )
            or 0
        )
        alert_count = (
            await db.scalar(select(func.count(JobAlert.id)).where(JobAlert.user_id == user.id)) or 0
        )
        muted_count = (
            await db.scalar(
                select(func.count(UserCompanyPref.id)).where(
                    UserCompanyPref.user_id == user.id,
                    UserCompanyPref.status == "muted",
                )
            )
            or 0
        )

        prof = await db.scalar(select(ResumeProfile).where(ResumeProfile.user_id == user.id))
        resume_status = "✅ Indexed" if prof else "⚠️ Upload Pending"

        await update.message.reply_text(
            f"📈 **Your JobPilot Stats:**\n\n"
            f"👤 **Account:** `{user.email or 'Connected'}`\n"
            f"📄 **Resume Profile:** {resume_status}\n"
            f"🕒 **Timezone:** `{user.timezone}`\n\n"
            f"📊 **Tracked Applications:** {app_count}\n"
            f"⏰ **Active Assessment Reminders:** {rem_count}\n"
            f"🎯 **Job Match Alerts Delivered:** {alert_count}\n"
            f"🔕 **Muted Companies:** {muted_count}\n",
            parse_mode=ParseMode.MARKDOWN,
        )


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /timezone <IANA_STRING> command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/timezone <IANA_TIMEZONE>`\n"
            "Example: `/timezone America/New_York` or `/timezone America/Los_Angeles`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    tz_input = args[0].strip()
    if not validate_timezone(tz_input):
        await update.message.reply_text(
            f"❌ `{tz_input}` is not a recognized IANA timezone.\n"
            "Please use standard names like `America/New_York`, `America/Chicago`, "
            "`America/Los_Angeles`, `Europe/London`, etc.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text(
                "❌ Your Telegram is not yet linked. Use `/link <user_id>` first."
            )
            return

        user.timezone = tz_input
        await db.commit()
        await update.message.reply_text(
            f"✅ **Timezone updated to:** `{tz_input}`\n"
            f"Reminders will now fire at 10:00 and 19:00 in `{tz_input}`.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pause command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        user.paused = True
        await db.commit()
        await update.message.reply_text(
            "⏸️ **Reminders paused.** Send `/resume` whenever you're ready to restart."
        )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("❌ Account not linked.")
            return

        user.paused = False
        await db.commit()
        await update.message.reply_text(
            "▶️ **Reminders resumed!** You will receive scheduled reminders as usual."
        )


async def delete_my_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_my_data command (privacy-minimal wipe and token revocation)."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = await db.scalar(stmt)
        if not user:
            await update.message.reply_text("No linked account found.")
            return

        # Fetch Gmail accounts to revoke refresh tokens
        acc_stmt = select(GmailAccount).where(GmailAccount.user_id == user.id)
        accounts = list((await db.scalars(acc_stmt)).all())

        for acc in accounts:
            try:
                plain_token = decrypt_token(acc.refresh_token_encrypted)
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": plain_token},
                        timeout=5.0,
                    )
            except Exception as exc:
                logger.warning("Failed to revoke Google token during delete_my_data: %s", exc)

        # Delete user (CASCADE deletes all related rows in all tables via DB foreign keys)
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()

        await update.message.reply_text(
            "🗑️ **All your data has been permanently deleted.**\n\n"
            "• All database records and history removed.\n"
            "• Google OAuth access tokens revoked.\n"
            "Thank you for using JobPilot!",
            parse_mode=ParseMode.MARKDOWN,
        )


async def applications_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /applications command: list tracked applications & outreach state."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            await update.message.reply_text("❌ Account not linked. Use `/link <user_id>` first.")
            return

        stmt = (
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.applied_at.desc().nullslast())
        )
        apps = list((await db.scalars(stmt)).all())

        if not apps:
            await update.message.reply_text(
                "📁 **No tracked job applications yet.**\n\n"
                "When you submit job applications, JobPilot automatically tracks confirmations "
                "and helps you with follow-ups and cold outreach nudges.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        lines = [f"📊 **Your Tracked Applications ({len(apps)}):**\n"]
        for idx, app in enumerate(apps, 1):
            company = await db.get(Company, app.company_id)
            comp_name = company.name if company else "Unknown Company"

            role_str = "Software Engineering"
            if app.job_posting_id:
                job = await db.get(JobPosting, app.job_posting_id)
                if job:
                    role_str = job.title

            outreach_stmt = (
                select(Outreach)
                .where(Outreach.application_id == app.id)
                .order_by(Outreach.created_at.desc())
            )
            outreaches = list((await db.scalars(outreach_stmt)).all())

            if any(o.kind == "cold_email_detected" for o in outreaches):
                outreach_status = "✉️ Cold Email Sent"
            elif any(o.kind in ("nudge_sent", "draft_generated") for o in outreaches):
                outreach_status = "📝 Nudge Sent"
            else:
                outreach_status = "⏳ No Outreach Logged"

            applied_date = app.applied_at.strftime("%b %d, %Y") if app.applied_at else "Recently"
            status_badge = app.status.upper()

            lines.append(
                f"**{idx}. {comp_name}** — `{status_badge}`\n"
                f"💼 Role: {role_str}\n"
                f"📅 Applied: {applied_date}\n"
                f"📡 Outreach: {outreach_status}\n"
            )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks (recur, dismiss, done, mute, draft, sent, snooze)."""
    query = update.callback_query
    if not query or not query.data or not update.effective_chat:
        return

    await query.answer()
    chat_id = update.effective_chat.id
    action, _, target_id_str = query.data.partition(":")

    now = datetime.datetime.now(datetime.UTC)
    orig_text = (
        query.message.text if isinstance(query.message, Message) and query.message.text else ""
    )

    async with await async_session_factory() as db:
        user = await db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if not user:
            logger.warning("Unauthorized callback attempt by chat %s", chat_id)
            return

        if action == "mute":
            try:
                company_id = uuid.UUID(target_id_str)
            except ValueError:
                return

            company = await db.get(Company, company_id)
            if not company:
                return

            pref_stmt = select(UserCompanyPref).where(
                UserCompanyPref.user_id == user.id,
                UserCompanyPref.company_id == company.id,
            )
            pref = await db.scalar(pref_stmt)
            if pref:
                pref.status = "muted"
            else:
                pref = UserCompanyPref(user_id=user.id, company_id=company.id, status="muted")
                db.add(pref)

            await db.commit()
            mute_msg = f"{orig_text}\n\n🔕 **Muted {company.name}.** (Alerts silenced)"
            await query.edit_message_text(
                text=mute_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "draft":
            try:
                app_id = uuid.UUID(target_id_str)
            except ValueError:
                return

            application = await db.get(Application, app_id)
            if not application or application.user_id != user.id:
                return

            company = await db.get(Company, application.company_id)
            comp_name = company.name if company else "Company"

            resume_prof = await db.scalar(
                select(ResumeProfile).where(ResumeProfile.user_id == user.id)
            )
            structured_profile = None
            if resume_prof and resume_prof.structured_json:
                structured_profile = StructuredResumeProfile.model_validate(
                    resume_prof.structured_json
                )

            role_title = None
            if application.job_posting_id:
                job = await db.get(JobPosting, application.job_posting_id)
                if job:
                    role_title = job.title

            drafter = ColdEmailDrafter()
            draft = await drafter.draft(
                candidate_profile=structured_profile,
                company_name=comp_name,
                role_title=role_title or "Software Engineering Intern",
            )

            outreach = Outreach(
                application_id=application.id,
                kind="draft_generated",
                contact_domain=company.domains[0] if company and company.domains else None,
            )
            db.add(outreach)
            await db.commit()

            draft_text = (
                f"{orig_text}\n\n"
                f"📝 **Cold Outreach Email Draft:**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"**Subject:** {draft.subject}\n\n"
                f"{draft.body}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 _Tip: Personalize with a recruiter's name and send from your linked email!_"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Mark as Sent",
                            callback_data=f"sent:{application.id}",
                        ),
                    ],
                ]
            )

            await query.edit_message_text(
                text=draft_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            return

        if action == "sent":
            try:
                app_id = uuid.UUID(target_id_str)
            except ValueError:
                return

            application = await db.get(Application, app_id)
            if not application or application.user_id != user.id:
                return

            company = await db.get(Company, application.company_id)
            outreach = Outreach(
                application_id=application.id,
                kind="cold_email_detected",
                contact_domain=company.domains[0] if company and company.domains else None,
            )
            db.add(outreach)
            await db.commit()

            sent_msg = (
                f"{orig_text}\n\n"
                f"✅ **Marked as Sent!** Outreach logged in your application tracker."
            )
            await query.edit_message_text(
                text=sent_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "snooze":
            try:
                app_id = uuid.UUID(target_id_str)
            except ValueError:
                return

            snooze_msg = (
                f"{orig_text}\n\n"
                f"⏰ **Nudge snoozed.** You can review applications anytime with `/applications`."
            )
            await query.edit_message_text(
                text=snooze_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Reminder actions (recur, dismiss, done)
        try:
            reminder_id = uuid.UUID(target_id_str)
        except ValueError:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        # Load reminder with user and event
        stmt = select(Reminder).where(Reminder.id == reminder_id)
        reminder = await db.scalar(stmt)

        if not reminder:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        if reminder.user_id != user.id:
            logger.warning(
                "Unauthorized callback attempt by chat %s for reminder %s",
                chat_id,
                reminder_id,
            )
            return

        event = await db.get(Event, reminder.event_id)

        if action == "recur":
            reminder.state = "recurring"
            next_fire = calculate_next_fire_slot(now, user.timezone)
            reminder.next_fire_at = next_fire
            user_tz = get_user_zone(user.timezone)
            local_fire = next_fire.astimezone(user_tz)
            await db.commit()

            await query.edit_message_text(
                text=(
                    f"{orig_text}\n\n"
                    f"🔁 **Recurring active!** Next reminder: "
                    f"**{local_fire.strftime('%b %d at %I:%M %p')}**"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "dismiss":
            reminder.state = "dismissed"
            if event:
                event.status = "dismissed"
            await db.commit()

            await query.edit_message_text(
                text=f"{orig_text}\n\n✖ **Reminder dismissed.**",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "done":
            reminder.state = "done"
            if event:
                event.status = "completed"
            await db.commit()

            await query.edit_message_text(
                text=f"{orig_text}\n\n🎉 **Great job! Marked as completed.**",
                parse_mode=ParseMode.MARKDOWN,
            )
