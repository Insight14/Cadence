"""Unit tests for ColdEmailDrafter."""

import json
from unittest.mock import AsyncMock

import pytest

from jobpilot.applications.drafter import ColdEmailDraft, ColdEmailDrafter
from jobpilot.resume.extractor import StructuredResumeProfile


@pytest.mark.asyncio
async def test_generate_draft_success() -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "subject": "UT Dallas CS - Stripe Backend Intern Interest",
            "body": "Hi there,\n\nI recently applied to the SWE Intern role at Stripe...",
        }
    )

    profile = StructuredResumeProfile(
        skills=["Python", "Go", "PostgreSQL"],
        domains=["Backend", "Distributed Systems"],
        project_themes=["Rideshare detection", "API gateways"],
        target_roles=["Backend Engineer Intern"],
        summary="Computer Science student with experience building distributed backends.",
    )

    drafter = ColdEmailDrafter(llm_client=mock_llm)
    draft = await drafter.generate_draft(
        profile=profile,
        company_name="Stripe",
        role_title="Software Engineer Intern",
    )

    assert isinstance(draft, ColdEmailDraft)
    assert draft.subject == "UT Dallas CS - Stripe Backend Intern Interest"
    assert "Stripe" in draft.body
    assert mock_llm.generate.called


@pytest.mark.asyncio
async def test_generate_draft_fallback_on_error() -> None:
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = Exception("LLM connection failed")

    profile = StructuredResumeProfile(
        skills=["React", "TypeScript"],
        domains=["Frontend"],
        project_themes=["Web UI"],
        target_roles=["Frontend Engineer"],
        summary="Frontend developer.",
    )

    drafter = ColdEmailDrafter(llm_client=mock_llm)
    draft = await drafter.generate_draft(
        profile=profile,
        company_name="Airbnb",
        role_title="Frontend Engineer Intern",
    )

    assert isinstance(draft, ColdEmailDraft)
    assert draft.subject == "Interest in Frontend Engineer Intern at Airbnb"
    assert "Airbnb" in draft.body
    assert "React, TypeScript" in draft.body
