"""Stage 2 LLM-based structured email classifier and extractor."""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jobpilot.classify.schemas import ClassificationResult
from jobpilot.llm.client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI email classifier for job seekers.
Analyze the provided email metadata and content to extract structured information.

Respond ONLY with a valid JSON object with EXACTLY this structure:
{
  "label": "oa" | "interview" | "application_confirmation" | "rejection" | "other",
  "confidence": <float between 0.0 and 1.0>,
  "company": "<Company Name>" | null,
  "role_title": "<Role / Title>" | null,
  "platform": "HackerRank" | "CodeSignal" | "HireVue" | "Karat" | null,
  "deadline_iso": "<ISO-8601 formatted datetime with timezone>" | null,
  "link": "<Direct link to assessment/interview/calendar>" | null
}

Guidelines:
- "oa": Online assessment, coding challenge, HackerRank/CodeSignal invitation, take-home.
- "interview": Invitation to schedule interview, recruiter screen, technical interview.
- "application_confirmation": Application submission acknowledgment ("thanks for applying").
- "rejection": Notice that company is not moving forward.
- "other": Newsletters, status updates with no action, irrelevant emails.
- If relative deadlines are mentioned ("within 7 days", "in 48 hours"), compute target ISO-8601.
- Confidence must reflect certainty of the classification and extracted fields.
"""


def _clean_json_response(raw_text: str) -> str:
    """Extract and clean raw JSON block from markdown codeblocks or surrounding text."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def resolve_relative_deadline(
    deadline_str: str | None,
    received_at: datetime | None,
) -> datetime | None:
    """Helper to parse and resolve ISO dates or relative timeframes relative to received_at."""
    if not deadline_str:
        return None

    # Try parsing as ISO format first
    try:
        dt = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        pass

    base_time = received_at or datetime.now(UTC)
    lower = deadline_str.lower()

    # Match "X days"
    days_match = re.search(r"(\d+)\s*(?:business\s+)?day", lower)
    if days_match:
        days = int(days_match.group(1))
        return base_time + timedelta(days=days)

    # Match "X hours"
    hours_match = re.search(r"(\d+)\s*hour", lower)
    if hours_match:
        hours = int(hours_match.group(1))
        return base_time + timedelta(hours=hours)

    # Match "X weeks"
    weeks_match = re.search(r"(\d+)\s*week", lower)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        return base_time + timedelta(weeks=weeks)

    return None


class LLMClassifier:
    """Stage 2 Classifier invoking LLM provider with retry and schema validation."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()

    async def classify(
        self,
        sender_domain: str | None,
        subject: str,
        body_snippet: str,
        received_at: datetime,
    ) -> ClassificationResult:
        """Classify email and extract structured job/assessment data."""
        # Trim body snippet to ~1500 chars for privacy & token efficiency
        trimmed_body = (body_snippet or "")[:1500]

        prompt = (
            f"Email Received Date: {received_at.isoformat()}\n"
            f"Sender Domain: {sender_domain or 'unknown'}\n"
            f"Subject: {subject}\n"
            f"Body:\n{trimmed_body}\n"
        )

        for attempt in range(2):  # 1 initial attempt + 1 retry on JSON error
            try:
                raw_response = await self.client.generate(prompt, system_prompt=SYSTEM_PROMPT)
                cleaned_json = _clean_json_response(raw_response)
                parsed_data: dict[str, Any] = json.loads(cleaned_json)

                # Pydantic validation
                result = ClassificationResult.model_validate(parsed_data)

                # Resolve relative deadline if needed
                if result.deadline_iso:
                    if isinstance(result.deadline_iso, str):
                        resolved = resolve_relative_deadline(result.deadline_iso, received_at)
                        result.deadline_iso = resolved

                # Low confidence fallback
                if result.confidence < 0.7:
                    logger.info(
                        "Classifier confidence %s below threshold 0.7; labeling as 'other'",
                        result.confidence,
                    )
                    return ClassificationResult(
                        label="other",
                        confidence=result.confidence,
                        company=result.company,
                        role_title=result.role_title,
                        platform=result.platform,
                        deadline_iso=None,
                        link=None,
                    )

                return result

            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "LLM JSON parsing/validation failed on attempt %d: %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 1:
                    logger.error("Failed to parse LLM response after 2 attempts.")
                    return ClassificationResult(
                        label="other",
                        confidence=0.0,
                        company=None,
                        role_title=None,
                        platform=None,
                        deadline_iso=None,
                        link=None,
                    )
                prompt += "\nNote: Your previous response was invalid. Output strict JSON only."

        return ClassificationResult(
            label="other",
            confidence=0.0,
            company=None,
            role_title=None,
            platform=None,
            deadline_iso=None,
            link=None,
        )
