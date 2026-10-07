"""Server-rendered onboarding and status routes using Jinja2."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import GmailAccount
from jobpilot.db.session import get_db_session

router = APIRouter(tags=["Onboarding"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def onboarding_home(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render the main onboarding dashboard."""
    connected_accounts: list[GmailAccount] = []
    db_connected = True
    try:
        accounts_query = select(GmailAccount).where(GmailAccount.status == "active")
        result = await db.scalars(accounts_query)
        connected_accounts = list(result.all())
    except Exception:
        db_connected = False

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "connected_accounts": connected_accounts,
            "db_connected": db_connected,
        },
    )
