"""Unit tests for FastAPI resume upload and profile retrieval routes."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.api.main import app
from jobpilot.db.models import User
from jobpilot.db.session import get_db_session
from jobpilot.embeddings.client import FakeEmbeddingsClient
from jobpilot.llm.client import FakeLLMClient


@pytest.mark.asyncio
async def test_upload_resume_endpoint(db_session: AsyncSession) -> None:
    # Set fake clients
    mock_llm = FakeLLMClient(
        default_response="""
        {
            "skills": ["Go", "Kubernetes"],
            "domains": ["Cloud", "DevOps"],
            "project_themes": ["Custom Kubernetes Operator"],
            "target_roles": ["Cloud Infrastructure Intern"],
            "graduation_year": 2025,
            "work_authorization": "US Citizen",
            "summary": "Cloud infrastructure enthusiast."
        }
        """
    )
    fake_embedder = FakeEmbeddingsClient(dimension=64)

    # Override get_db_session and dependencies
    async def override_get_db() -> AsyncSession:
        return db_session

    app.dependency_overrides[get_db_session] = override_get_db

    # Create user
    user = User(email="cloud_student@college.edu")
    db_session.add(user)
    await db_session.commit()

    from unittest.mock import patch

    transport = ASGITransport(app=app)
    with (
        patch("jobpilot.resume.extractor.get_llm_client", return_value=mock_llm),
        patch("jobpilot.resume.service.get_embeddings_client", return_value=fake_embedder),
        patch("jobpilot.api.routes_onboarding.get_embeddings_client", return_value=fake_embedder),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Upload TXT resume
            files = {"file": ("resume.txt", b"Cloud engineer resume with Go and K8s", "text/plain")}
            data = {"user_id": str(user.id)}

            # Upload
            resp = await client.post("/resume/upload", data=data, files=files)
            assert resp.status_code == 200
            json_resp = resp.json()
            assert json_resp["status"] == "success"
            assert "Go" in json_resp["profile"]["skills"]

            # 2. Get Profile
            get_resp = await client.get(f"/resume/profile?user_id={user.id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["profile"]["graduation_year"] == 2025

    app.dependency_overrides.clear()
