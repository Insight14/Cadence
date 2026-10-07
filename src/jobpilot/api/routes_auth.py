"""Google OAuth 2.0 flow routes for Gmail read-only access."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.config import get_settings
from jobpilot.db.models import GmailAccount, User, utc_now
from jobpilot.db.session import get_db_session
from jobpilot.gmail.client import GMAIL_SCOPES
from jobpilot.security.crypto import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Authentication"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_oauth_flow(state: str | None = None) -> Flow:
    """Create a Flow instance configured with client secrets and redirect URI."""
    settings = get_settings()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GMAIL_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


@router.get("/start")
async def google_auth_start(
    user_id: str | None = None,
) -> RedirectResponse:
    """Initiate Google OAuth 2.0 authorization flow."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth credentials are not configured in settings.",
        )

    # Pass user_id (if existing) in state or generate a state UUID
    state = user_id or str(uuid.uuid4())
    flow = get_oauth_flow(state=state)

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback", response_class=HTMLResponse)
async def google_auth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code returned by Google"),
    state: str = Query(default="", description="State token returned by Google"),
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Handle Google OAuth 2.0 callback, exchange code for refresh token, and persist account."""
    flow = get_oauth_flow(state=state)

    try:
        # Fetch tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials

        if not credentials.refresh_token:
            logger.warning("No refresh token returned by Google.")

        # Build Gmail service to get user profile (email and initial historyId)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()

        google_email = profile.get("emailAddress", "")
        initial_history_id = str(profile.get("historyId", ""))

        # Resolve or create User
        user: User | None = None
        if state:
            try:
                user_uuid = uuid.UUID(state)
                user = await db.get(User, user_uuid)
            except ValueError:
                pass

        if not user:
            # Check if user with this email exists
            stmt = select(User).where(User.email == google_email)
            user = await db.scalar(stmt)

        if not user:
            user = User(
                email=google_email,
                timezone="America/Chicago",
            )
            db.add(user)
            await db.flush()

        # Encrypt the refresh token
        encrypted_token = encrypt_token(credentials.refresh_token or "")

        # Find or create GmailAccount
        stmt_acc = select(GmailAccount).where(
            GmailAccount.user_id == user.id,
            GmailAccount.google_email == google_email,
        )
        account = await db.scalar(stmt_acc)

        if account:
            account.refresh_token_encrypted = encrypted_token
            account.history_id = initial_history_id
            account.status = "active"
            account.last_polled_at = utc_now()
        else:
            account = GmailAccount(
                user_id=user.id,
                google_email=google_email,
                refresh_token_encrypted=encrypted_token,
                history_id=initial_history_id,
                status="active",
            )
            db.add(account)

        await db.commit()
        logger.info("Successfully linked Gmail account %s for user %s", google_email, user.id)

        return templates.TemplateResponse(
            request=request,
            name="auth_success.html",
            context={
                "google_email": google_email,
                "user_id": str(user.id),
            },
        )

    except Exception as exc:
        logger.exception("Error handling OAuth callback: %s", exc)
        return templates.TemplateResponse(
            request=request,
            name="auth_error.html",
            context={
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
