"""Gmail API client factory and credentials management."""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from jobpilot.config import get_settings
from jobpilot.security.crypto import decrypt_token

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_gmail_service(encrypted_refresh_token: str) -> Resource:
    """Build an authorized Gmail API Resource instance using encrypted refresh token."""
    settings = get_settings()
    plain_refresh_token = decrypt_token(encrypted_refresh_token)

    creds = Credentials(
        None,  # Access token will be automatically refreshed
        refresh_token=plain_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=GMAIL_SCOPES,
    )

    # Validate and refresh token if needed
    if not creds.valid:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
