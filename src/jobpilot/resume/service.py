"""Resume processing, embedding generation, and company watch matching service."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import Company, ResumeProfile, UserCompanyPref
from jobpilot.embeddings.client import BaseEmbeddingsClient, get_embeddings_client
from jobpilot.resume.extractor import (
    ResumeProfileExtractor,
    StructuredResumeProfile,
)
from jobpilot.resume.parser import extract_resume_text

logger = logging.getLogger(__name__)


def build_profile_embed_text(profile: StructuredResumeProfile) -> str:
    """Combine structured profile attributes into dense textual representation for embedding."""
    parts: list[str] = []
    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills)}")
    if profile.domains:
        parts.append(f"Domains: {', '.join(profile.domains)}")
    if profile.project_themes:
        parts.append(f"Projects: {', '.join(profile.project_themes)}")
    if profile.target_roles:
        parts.append(f"Target Roles: {', '.join(profile.target_roles)}")
    if profile.summary:
        parts.append(f"Summary: {profile.summary}")

    return "\n".join(parts)


async def auto_match_company_tags(
    session: AsyncSession,
    user_id: uuid.UUID,
    profile_domains: list[str],
) -> list[Company]:
    """Auto-add companies as 'watch' if their tags match user's profile domains."""
    if not profile_domains:
        return []

    domain_set = {d.lower().strip() for d in profile_domains if d.strip()}
    stmt_companies = select(Company)
    all_companies = list((await session.scalars(stmt_companies)).all())

    stmt_prefs = select(UserCompanyPref).where(UserCompanyPref.user_id == user_id)
    existing_prefs = {p.company_id: p for p in (await session.scalars(stmt_prefs)).all()}

    auto_watched: list[Company] = []

    for comp in all_companies:
        comp_tags = {t.lower().strip() for t in (comp.tags or [])}
        # Check intersection
        if domain_set.intersection(comp_tags):
            if comp.id not in existing_prefs:
                new_pref = UserCompanyPref(
                    user_id=user_id,
                    company_id=comp.id,
                    status="watch",
                )
                session.add(new_pref)
                auto_watched.append(comp)
                logger.info(
                    "Auto-watched company %s for user %s based on matching domain tags %s",
                    comp.name,
                    user_id,
                    domain_set.intersection(comp_tags),
                )

    return auto_watched


async def process_and_save_resume(
    session: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    file_bytes: bytes,
    extractor: ResumeProfileExtractor | None = None,
    embeddings_client: BaseEmbeddingsClient | None = None,
) -> tuple[ResumeProfile, StructuredResumeProfile, list[Company]]:
    """Extract text, parse structured profile, generate embedding, and persist."""
    logger.info("Processing resume upload '%s' for user %s", filename, user_id)

    # 1. In-memory text extraction
    raw_text = extract_resume_text(filename, file_bytes)

    # 2. Structured profile extraction
    ext = extractor or ResumeProfileExtractor()
    profile = await ext.extract_profile(raw_text)

    # 3. Vector embedding generation
    embedder = embeddings_client or get_embeddings_client()
    embed_input = build_profile_embed_text(profile)
    vector = await embedder.embed_text(embed_input)

    # 4. Upsert ResumeProfile record
    stmt = select(ResumeProfile).where(ResumeProfile.user_id == user_id)
    existing_profile = await session.scalar(stmt)

    if existing_profile:
        existing_profile.structured_json = profile.model_dump()
        existing_profile.embedding = vector
        res_profile = existing_profile
    else:
        res_profile = ResumeProfile(
            user_id=user_id,
            structured_json=profile.model_dump(),
            embedding=vector,
        )
        session.add(res_profile)

    await session.flush()

    # 5. Auto-watch matched companies by tags
    auto_watched = await auto_match_company_tags(session, user_id, profile.domains)

    await session.commit()
    logger.info(
        "Successfully saved resume profile for user %s (%d skills, %d domains, %d watched)",
        user_id,
        len(profile.skills),
        len(profile.domains),
        len(auto_watched),
    )

    return res_profile, profile, auto_watched
