"""Unit tests for structured resume profile LLM extraction."""

import pytest

from jobpilot.llm.client import BaseLLMClient
from jobpilot.resume.extractor import (
    ResumeProfileExtractor,
    StructuredResumeProfile,
)


class MockResumeLLMClient(BaseLLMClient):
    """Mock LLM client returning realistic JSON structured resume output."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return self.response_text


@pytest.mark.asyncio
async def test_extract_profile_success() -> None:
    json_response = """
    {
        "skills": ["Python", "PyTorch", "FastAPI", "PostgreSQL", "Docker"],
        "domains": ["Machine Learning", "Backend Systems", "Distributed Systems"],
        "project_themes": ["LLM Inference Optimization", "RAG Pipeline"],
        "target_roles": ["Machine Learning Engineer Intern", "Backend Engineer"],
        "graduation_year": 2026,
        "work_authorization": "US Citizen",
        "summary": "Junior CS student at CMU specializing in ML systems and scalable backends."
    }
    """

    mock_llm = MockResumeLLMClient(json_response)
    extractor = ResumeProfileExtractor(llm_client=mock_llm)

    profile = await extractor.extract_profile("Fake resume text for candidate...")

    assert isinstance(profile, StructuredResumeProfile)
    assert "Python" in profile.skills
    assert "Machine Learning" in profile.domains
    assert profile.graduation_year == 2026
    assert profile.work_authorization == "US Citizen"
    assert "CMU" in (profile.summary or "")


@pytest.mark.asyncio
async def test_extract_profile_markdown_codeblock_cleanup() -> None:
    json_response = """```json
    {
        "skills": ["Rust", "C++"],
        "domains": ["Robotics", "Embedded"],
        "project_themes": ["Autonomous Drone Navigation"],
        "target_roles": ["Robotics Software Engineer"],
        "graduation_year": 2025,
        "work_authorization": "F-1 OPT",
        "summary": "Robotics engineering student."
    }
    ```"""
    mock_llm = MockResumeLLMClient(json_response)
    extractor = ResumeProfileExtractor(llm_client=mock_llm)

    profile = await extractor.extract_profile("Robotics resume text...")

    assert "Rust" in profile.skills
    assert "Robotics" in profile.domains
    assert profile.graduation_year == 2025


@pytest.mark.asyncio
async def test_extract_profile_fallback_on_invalid_json() -> None:
    mock_llm = MockResumeLLMClient("Not a valid json response")
    extractor = ResumeProfileExtractor(llm_client=mock_llm)

    profile = await extractor.extract_profile("Some resume text...")

    # Should fallback gracefully without raising an exception
    assert isinstance(profile, StructuredResumeProfile)
    assert "Python" in profile.skills
    assert "software engineering" in profile.domains
