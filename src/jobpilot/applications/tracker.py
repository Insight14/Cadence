"""Application tracking, Sent folder cold-outreach verification, and Telegram nudges."""

import logging
import uuid

from googleapiclient.discovery import Resource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from jobpilot.applications.drafter import ColdEmailDrafter
from jobpilot.applications.nudge import (
    build_linkedin_hiring_manager_search_url,
    build_linkedin_recruiter_search_url,
)
from jobpilot.bot.app import get_telegram_app, send_telegram_alert
from jobpilot.db.models import (
    Application,
    Company,
    Outreach,
    ProcessedEmail,
    User,
)
from jobpilot.gmail.sent_search import check_prior_outreach

logger = logging.getLogger(__name__)


class ApplicationTracker:
    """Detects application confirmations, checks Sent folder, and orchestrates cold outreach."""

    def __init__(self, drafter: ColdEmailDrafter | None = None) -> None:
        self.drafter = drafter or ColdEmailDrafter()

    async def resolve_or_create_company(
        self,
        session: AsyncSession,
        company_name: str | None,
        sender_domain: str | None,
    ) -> Company:
        """Find existing company by name/domain or create placeholder."""
        name = company_name.strip() if company_name else None

        if name:
            stmt = select(Company).where(Company.name.ilike(name))
            existing = await session.scalar(stmt)
            if existing:
                return existing

        if sender_domain:
            clean_dom = sender_domain.lower().strip().lstrip("@")
            stmt_dom = select(Company)
            all_comps = list((await session.scalars(stmt_dom)).all())
            for c in all_comps:
                if clean_dom in [d.lower() for d in (c.domains or [])]:
                    return c

        # Create new company record
        default_comp = sender_domain.split(".")[0].capitalize() if sender_domain else "Unknown"
        comp_name = name or default_comp
        domains_list = [sender_domain] if sender_domain else []
        new_company = Company(
            name=comp_name,
            ats="other",
            board_token=comp_name.lower().replace(" ", "-"),
            domains=domains_list,
            tags=[],
        )
        session.add(new_company)
        await session.flush()
        return new_company

    async def process_confirmation_email(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        proc_email: ProcessedEmail,
        company_name: str | None,
        role_title: str | None,
        gmail_service: Resource | None = None,
        bot: Bot | None = None,
    ) -> Application:
        """Process application confirmation, check Sent folder, and dispatch outreach nudge."""
        company = await self.resolve_or_create_company(
            session=session,
            company_name=company_name,
            sender_domain=proc_email.sender_domain,
        )

        # 1. Upsert Application record
        stmt = select(Application).where(
            Application.user_id == user_id,
            Application.company_id == company.id,
        )
        application = await session.scalar(stmt)

        if not application:
            application = Application(
                user_id=user_id,
                company_id=company.id,
                status="applied",
                applied_at=proc_email.received_at,
                confirmation_email_id=proc_email.id,
            )
            session.add(application)
            await session.flush()
        else:
            application.confirmation_email_id = proc_email.id
            await session.flush()

        # 2. Check user's Sent folder for prior outreach
        domains_to_check = list(company.domains) if company.domains else []
        if proc_email.sender_domain and proc_email.sender_domain not in domains_to_check:
            domains_to_check.append(proc_email.sender_domain)

        has_sent_outreach = False
        matching_domain = None

        if gmail_service:
            has_sent_outreach, matching_domain = check_prior_outreach(
                service=gmail_service,
                company_domains=domains_to_check,
                days_back=60,
            )

        if has_sent_outreach:
            # User already sent a cold email! Record detection and remain silent
            outreach_rec = Outreach(
                application_id=application.id,
                kind="cold_email_detected",
                contact_domain=matching_domain or proc_email.sender_domain,
            )
            session.add(outreach_rec)
            await session.commit()
            logger.info(
                "Prior outreach found for user %s to %s. Skipping cold outreach nudge.",
                user_id,
                company.name,
            )
            return application

        # 3. No prior outreach: generate draft and send Telegram nudge
        outreach_rec = Outreach(
            application_id=application.id,
            kind="nudge_sent",
            contact_domain=proc_email.sender_domain,
        )
        session.add(outreach_rec)
        await session.commit()

        user = await session.get(User, user_id)
        if user and user.telegram_chat_id and not user.paused:
            await self.send_outreach_nudge(
                session=session,
                user=user,
                application=application,
                company=company,
                role_title=role_title,
                bot=bot,
            )

        return application

    async def send_outreach_nudge(
        self,
        session: AsyncSession,
        user: User,
        application: Application,
        company: Company,
        role_title: str | None,
        bot: Bot | None = None,
    ) -> int | None:
        """Send a formatted Telegram nudge with LinkedIn recruiter links and draft buttons."""
        if not user.telegram_chat_id:
            return None

        target_bot = bot or get_telegram_app().bot
        role = role_title or "Software Engineering Intern"
        recruiter_link = build_linkedin_recruiter_search_url(company.name)
        manager_link = build_linkedin_hiring_manager_search_url(company.name, role_title)

        tip = (
            "💡 _Tip: Sending a personalized note to a university recruiter or "
            "engineering manager boosts interview rates by ~3x._\n"
        )
        text_lines = [
            f"📨 **Application Confirmed for {company.name}!**\n",
            f"💼 **Role:** {role}",
            f"🏢 **Company:** {company.name}\n",
            tip,
            f"🔍 [Find Recruiters on LinkedIn]({recruiter_link})",
            f"👔 [Find Hiring Managers on LinkedIn]({manager_link})\n",
        ]

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📝 View Cold Email Draft",
                        callback_data=f"draft:{application.id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "✅ Mark as Sent",
                        callback_data=f"sent:{application.id}",
                    ),
                    InlineKeyboardButton(
                        "⏰ Snooze",
                        callback_data=f"snooze:{application.id}",
                    ),
                ],
            ]
        )

        return await send_telegram_alert(
            bot=target_bot,
            chat_id=user.telegram_chat_id,
            text="\n".join(text_lines),
            reply_markup=keyboard,
        )
