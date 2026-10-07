"""Unit tests for the health check endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from jobpilot.api.main import app


@pytest.mark.asyncio
async def test_healthz_endpoint() -> None:
    """Test that /healthz returns 200 OK with proper status payload."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "jobpilot-api"
    assert "version" in data
