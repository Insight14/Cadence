"""Job matching engine: vector similarity, hard constraint filtering, and alert dispatching."""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from jobpilot.db.models import Company, JobAlert, JobPosting, ResumeProfile, User, UserCompanyPref
from jobpilot.embeddings.client import BaseEmbeddingsClient, get_embeddings_client
from jobpilot.llm.client import BaseLLMClient, get_llm_client
from jobpilot.resume.extractor import StructuredResumeProfile

logger = logging.getLogger(__name__)


def compute_cosine_similarity(v1: list[float] | None, v2: list[float] | None) -> float:
    """Compute cosine similarity between two float vectors in [0.0, 1.0]."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(v1, v2, strict=False))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    sim = dot_product / (norm_a * norm_b)
    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, (sim + 1.0) / 2.0 if sim < 0 else sim))


@dataclass(frozen=True)
class JobMatch:
    """A scored and filtered match between a user's profile and a job posting."""

    job: JobPosting
    company: Company
    similarity_score: float
    why_matched: str | None = None


BLURB_PROMPT_TEMPLATE = """You are an AI career advisor.
Generate a concise 1-2 sentence reason why this job posting matches the candidate's profile.

CANDIDATE PROFILE:
Skills: {skills}
Domain Interests: {domains}
Project Themes: {projects}
Summary: {summary}

JOB POSTING:
Company: {company}
Role: {title}
Location: {location}
Description Snippet:
{description}

Requirement: Write strictly 1-2 punchy sentences highlighting specific matching skills or themes.
"""


class JobMatcher:
    """Ranks and filters job postings against candidate resume profiles."""

    def __init__(
        self,
        embeddings_client: BaseEmbeddingsClient | None = None,
        llm_client: BaseLLMClient | None = None,
    ) -> None:
        self.embeddings_client = embeddings_client or get_embeddings_client()
        self.llm_client = llm_client or get_llm_client()

    async def generate_match_blurb(
        self,
        profile: StructuredResumeProfile,
        job: JobPosting,
        company: Company,
    ) -> str:
        """Generate a personalized 1-2 sentence 'Why this matches you' blurb using LLM."""
        prompt = BLURB_PROMPT_TEMPLATE.format(
            skills=", ".join(profile.skills[:8]),
            domains=", ".join(profile.domains[:5]),
            projects=", ".join(profile.project_themes[:3]),
            summary=profile.summary or "Computer Science student",
            company=company.name,
            title=job.title,
            location=job.location or "Not specified",
            description=(job.description_text or "")[:1000],
        )
        try:
            blurb = await self.llm_client.generate(prompt)
            return blurb.strip().strip('"')
        except Exception as exc:
            logger.warning("Failed to generate match blurb via LLM: %s", exc)
            domain_summary = ", ".join(profile.domains[:2]) or "software engineering"
            return f"Matches your background in {domain_summary}."

    async def find_matches_for_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        min_score: float = 0.60,
        max_matches: int = 10,
    ) -> list[JobMatch]:
        """Query open jobs, apply vector similarity and hard filters, and return scored matches."""
        # 1. Fetch user resume profile
        stmt_prof = select(ResumeProfile).where(ResumeProfile.user_id == user_id)
        profile_row = await session.scalar(stmt_prof)
        if not profile_row or not profile_row.embedding:
            logger.debug("User %s has no active resume profile or embedding.", user_id)
            return []

        profile_data = StructuredResumeProfile.model_validate(profile_row.structured_json)
        user_vector: list[float] = list(profile_row.embedding)

        # 2. Fetch user company preferences (muted / watched)
        stmt_prefs = select(UserCompanyPref).where(UserCompanyPref.user_id == user_id)
        prefs = list((await session.scalars(stmt_prefs)).all())
        muted_company_ids = {p.company_id for p in prefs if p.status == "muted"}

        # 3. Fetch already alerted job IDs to prevent duplicate notifications
        stmt_alerts = select(JobAlert.job_posting_id).where(JobAlert.user_id == user_id)
        alerted_job_ids = set((await session.scalars(stmt_alerts)).all())

        # 4. Fetch open job postings with company
        stmt_jobs = (
            select(JobPosting, Company)
            .join(Company, JobPosting.company_id == Company.id)
            .where(JobPosting.is_open.is_(True))
        )
        job_pairs = list((await session.execute(stmt_jobs)).all())

        scored_matches: list[tuple[JobPosting, Company, float]] = []

        for job, company in job_pairs:
            if company.id in muted_company_ids:
                continue
            if job.id in alerted_job_ids:
                continue

            # Compute similarity score
            if job.embedding is not None:
                job_vector = list(job.embedding)
                sim = compute_cosine_similarity(user_vector, job_vector)
            else:
                # Fallback: estimate similarity from title & company tags match
                sim = (
                    0.70
                    if any(
                        d.lower() in [t.lower() for t in company.tags] for d in profile_data.domains
                    )
                    else 0.50
                )

            if sim >= min_score:
                scored_matches.append((job, company, sim))

        # Sort by similarity score descending
        scored_matches.sort(key=lambda x: x[2], reverse=True)
        top_candidates = scored_matches[:max_matches]

        matches: list[JobMatch] = []
        for job, company, score in top_candidates:
            blurb = await self.generate_match_blurb(profile_data, job, company)
            matches.append(
                JobMatch(
                    job=job,
                    company=company,
                    similarity_score=score,
                    why_matched=blurb,
                )
            )

        return matches

    async def dispatch_job_alerts_for_user(
        self,
        session: AsyncSession,
        user: User,
        matches: list[JobMatch],
        bot: Bot | None = None,
    ) -> int:
        """Send formatted Telegram alert messages and record JobAlert rows."""
        from jobpilot.bot.app import get_telegram_app, send_telegram_alert

        if not user.telegram_chat_id or user.paused:
            return 0

        target_bot = bot
        if target_bot is None:
            target_bot = get_telegram_app().bot

        sent_count = 0
        now = datetime.now(UTC)

        for match in matches:
            job = match.job
            company = match.company
            score_pct = int(match.similarity_score * 100)

            text_lines = [
                "🎯 **New Matching Role Dropped!**\n",
                f"🏢 **Company:** {company.name}",
                f"💼 **Role:** {job.title}",
                f"📍 **Location:** {job.location or 'Not specified'}",
                f"📊 **Match Affinity:** **{score_pct}%**",
            ]
            if match.why_matched:
                text_lines.append(f"\n💡 _{match.why_matched}_\n")

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🚀 Apply Directly", url=job.url),
                    ],
                    [
                        InlineKeyboardButton(
                            f"🔕 Mute {company.name}",
                            callback_data=f"mute:{company.id}",
                        ),
                    ],
                ]
            )

            msg_id = await send_telegram_alert(
                bot=target_bot,
                chat_id=user.telegram_chat_id,
                text="\n".join(text_lines),
                reply_markup=keyboard,
            )

            if msg_id is not None:
                alert = JobAlert(
                    user_id=user.id,
                    job_posting_id=job.id,
                    score=match.similarity_score,
                    sent_at=now,
                )
                session.add(alert)
                sent_count += 1

        if sent_count > 0:
            await session.commit()
            logger.info("Dispatched %d job alert(s) to user %s", sent_count, user.id)

        return sent_count
