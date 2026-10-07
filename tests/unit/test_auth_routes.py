"""Unit tests for Google OAuth authentication routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from jobpilot.api.main import app
from jobpilot.config import Settings


@pytest.mark.asyncio
async def test_google_auth_start_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that /auth/google/start generates Google authorization URL redirect."""
    test_settings = Settings(
        google_client_id="mock_client_id.apps.googleusercontent.com",
        google_client_secret="mock_secret_key",
        google_redirect_uri="http://localhost:8000/auth/google/callback",
    )
    monkeypatch.setattr("jobpilot.api.routes_auth.get_settings", lambda: test_settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        response = await client.get("/auth/google/start")

    assert response.status_code == 302
    location = response.headers.get("location", "")
    assert "accounts.google.com" in location
    assert "mock_client_id" in location
    assert "gmail.readonly" in location
