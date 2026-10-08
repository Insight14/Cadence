"""Structured resume profile extraction using LLM."""

import json
import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.llm.client import BaseLLMClient, get_llm_client

logger = logging.getLogger(__name__)


class StructuredResumeProfile(BaseModel):
    """Structured representation of a student or new-grad candidate resume."""

    model_config = ConfigDict(populate_by_name=True)

    skills: list[str] = Field(
        default_factory=list,
        description="Programming languages, frameworks, developer tools, and databases.",
    )
    domains: list[str] = Field(
        default_factory=list,
        description="Core domain interests (e.g. autonomy, machine learning, systems, fintech).",
    )
    project_themes: list[str] = Field(
        default_factory=list,
        description="Key technical projects, problem spaces, or focus areas.",
    )
    graduation_year: int | None = Field(
        default=None,
        alias="grad_year",
        description="Expected or actual graduation year (e.g. 2025, 2026, 2027).",
    )
    work_authorization: str = Field(
        default="US Citizen / Permanent Resident",
        description="Work authorization status (e.g. 'US Citizen', 'F-1 OPT/CPT').",
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Target job titles (e.g. ['Software Engineer Intern', 'ML Engineer']).",
    )
    location_preferences: list[str] = Field(
        default_factory=list,
        description="Preferred locations (e.g. ['San Francisco, CA', 'New York, NY', 'Remote']).",
    )
    summary: str | None = Field(
        default=None,
        description="Concise 1-2 sentence professional summary.",
    )

    @property
    def grad_year(self) -> int | None:
        """Alias property for graduation_year."""
        return self.graduation_year


EXTRACTION_PROMPT_TEMPLATE = """You are an expert technical recruiter and resume parser.

Extract structured information from the candidate resume into strict JSON matching schema:

RESUME TEXT:
\"\"\"
{resume_text}
\"\"\"

SCHEMA REQUIREMENT (Respond ONLY with valid JSON):
{{
  "skills": ["Python", "C++", "React", "PyTorch", "Docker", "PostgreSQL"],
  "domains": ["autonomy", "distributed systems", "machine learning", "fintech"],
  "project_themes": ["Autonomous vehicle motion planning", "High-throughput message queue"],
  "grad_year": 2026,
  "work_authorization": "US Citizen / Permanent Resident",
  "target_roles": ["Software Engineer Intern", "Robotics Engineer Intern"],
  "location_preferences": ["San Francisco, CA", "Remote"],
  "summary": "Junior CS student with experience in high-performance computing and robotics."
}}

Guidelines:
1. Normalize domain tags to lowercase matching industry standards.
2. If grad year is not explicitly stated, estimate from the latest education dates or leave null.
3. If work authorization is not mentioned, default to 'US Citizen / Permanent Resident'.
4. Respond strictly with raw JSON. No markdown code fences, no extra preamble.
"""


class ResumeProfileExtractor:
    """Extracts structured candidate profile from raw resume text using LLM."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self.llm_client = llm_client or get_llm_client()

    def _clean_json_response(self, text: str) -> str:
        """Strip markdown code blocks and whitespace from LLM output."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    async def extract_profile(self, resume_text: str) -> StructuredResumeProfile:
        """Parse resume text and return structured profile validated with Pydantic."""
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            resume_text=resume_text[:6000],  # Truncate to prevent token overflows
        )

        for attempt in range(2):
            try:
                raw_response = await self.llm_client.generate(prompt)
                cleaned = self._clean_json_response(raw_response)
                parsed = json.loads(cleaned)
                return StructuredResumeProfile.model_validate(parsed)
            except Exception as exc:
                logger.warning(
                    "Resume structured extraction attempt %d failed: %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 1:
                    # Final fallback: return minimal profile
                    return StructuredResumeProfile(
                        skills=["Python"],
                        domains=["software engineering"],
                        project_themes=[],
                        summary="Candidate profile extracted with default values.",
                    )

        return StructuredResumeProfile()
