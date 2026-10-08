"""Server-rendered onboarding, status, and resume management routes."""

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import Company, GmailAccount, ResumeProfile, User, UserCompanyPref
from jobpilot.db.session import get_db_session
from jobpilot.embeddings.client import get_embeddings_client
from jobpilot.resume.extractor import StructuredResumeProfile
from jobpilot.resume.service import build_profile_embed_text, process_and_save_resume

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Onboarding"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class UpdateProfileRequest(BaseModel):
    """Payload for manually editing structured resume profile fields."""

    user_id: uuid.UUID
    skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    project_themes: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    graduation_year: int | None = None
    work_authorization: str | None = None
    summary: str | None = None


@router.get("/", response_class=HTMLResponse)
async def onboarding_home(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render the main onboarding and candidate dashboard."""
    connected_accounts: list[GmailAccount] = []
    first_user_id: str | None = None
    db_connected = True
    resume_profile: dict[str, Any] | None = None
    watched_companies: list[Company] = []

    try:
        accounts_query = select(GmailAccount).where(GmailAccount.status == "active")
        result = await db.scalars(accounts_query)
        connected_accounts = list(result.all())
        if connected_accounts:
            first_user_id = str(connected_accounts[0].user_id)
        else:
            # Check if there is any user in the system
            first_user = await db.scalar(select(User).limit(1))
            if first_user:
                first_user_id = str(first_user.id)

        if first_user_id:
            uid = uuid.UUID(first_user_id)
            prof_row = await db.scalar(select(ResumeProfile).where(ResumeProfile.user_id == uid))
            if prof_row and prof_row.structured_json:
                resume_profile = prof_row.structured_json

            # Fetch watched companies
            stmt_watch = (
                select(Company)
                .join(UserCompanyPref, UserCompanyPref.company_id == Company.id)
                .where(
                    UserCompanyPref.user_id == uid,
                    UserCompanyPref.status == "watch",
                )
            )
            watched_companies = list((await db.scalars(stmt_watch)).all())

    except Exception as exc:
        logger.warning("Error fetching dashboard status: %s", exc)
        db_connected = False

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "connected_accounts": connected_accounts,
            "first_user_id": first_user_id,
            "db_connected": db_connected,
            "resume_profile": resume_profile,
            "watched_companies": watched_companies,
        },
    )


@router.post("/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Upload resume (PDF/DOCX/TXT) strictly in memory, parse profile, and compute embeddings."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    # Target user resolution
    target_user_id: uuid.UUID
    if user_id:
        try:
            target_user_id = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format.") from None
    else:
        # Resolve from active gmail or first user
        acc = await db.scalar(select(GmailAccount).where(GmailAccount.status == "active").limit(1))
        if acc:
            target_user_id = acc.user_id
        else:
            first_user = await db.scalar(select(User).limit(1))
            if not first_user:
                # Create default user for onboarding
                new_user = User(email="student@jobpilot.local")
                db.add(new_user)
                await db.commit()
                target_user_id = new_user.id
            else:
                target_user_id = first_user.id

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        res_profile, structured, auto_watched = await process_and_save_resume(
            session=db,
            user_id=target_user_id,
            filename=file.filename,
            file_bytes=content_bytes,
        )
        return JSONResponse(
            content={
                "status": "success",
                "message": "Resume parsed and matching profile saved successfully.",
                "user_id": str(target_user_id),
                "profile": structured.model_dump(),
                "auto_watched_companies": [
                    {"id": str(c.id), "name": c.name, "tags": c.tags} for c in auto_watched
                ],
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to process resume upload: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to process resume: {exc}") from exc


@router.get("/resume/profile")
async def get_resume_profile(
    user_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Retrieve structured resume profile for a given user."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format.") from None

    prof_row = await db.scalar(select(ResumeProfile).where(ResumeProfile.user_id == uid))
    if not prof_row or not prof_row.structured_json:
        raise HTTPException(status_code=404, detail="No resume profile found for this user.")

    return JSONResponse(content={"profile": prof_row.structured_json})


@router.post("/resume/profile")
async def update_resume_profile(
    payload: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Manually update structured profile fields and recompute vector embeddings."""
    prof_row = await db.scalar(
        select(ResumeProfile).where(ResumeProfile.user_id == payload.user_id)
    )
    if not prof_row:
        raise HTTPException(status_code=404, detail="No resume profile found to update.")

    updated_profile = StructuredResumeProfile(
        skills=payload.skills,
        domains=payload.domains,
        project_themes=payload.project_themes,
        target_roles=payload.target_roles,
        graduation_year=payload.graduation_year,
        work_authorization=payload.work_authorization,
        summary=payload.summary,
    )

    embedder = get_embeddings_client()
    embed_text = build_profile_embed_text(updated_profile)
    vector = await embedder.embed_text(embed_text)

    prof_row.structured_json = updated_profile.model_dump()
    prof_row.embedding = vector
    await db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Profile updated and re-embedded successfully.",
            "profile": updated_profile.model_dump(),
        }
    )
