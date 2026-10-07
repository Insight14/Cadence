"""Pydantic models for email classification and extraction."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EmailLabel = Literal[
    "oa",
    "interview",
    "application_confirmation",
    "rejection",
    "other",
]


class ClassificationResult(BaseModel):
    """Structured output from Stage 2 LLM classifier."""

    label: EmailLabel = Field(
        description="Classification label: oa, interview, confirmation, rejection, or other"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    company: str | None = Field(
        default=None,
        description="Name of the hiring company / organization",
    )
    role_title: str | None = Field(
        default=None,
        description="Job role or internship title",
    )
    platform: str | None = Field(
        default=None,
        description="Platform name if applicable (HackerRank, CodeSignal, HireVue, Karat, etc.)",
    )
    deadline_iso: datetime | str | None = Field(
        default=None,
        description="Resolved ISO-8601 deadline with timezone if detected, otherwise null",
    )
    link: str | None = Field(
        default=None,
        description="Direct link to the assessment, interview portal, or scheduling link",
    )
