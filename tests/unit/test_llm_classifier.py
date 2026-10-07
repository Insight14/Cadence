"""Unit tests for Stage 2 LLM-based structured classifier."""

import json
from datetime import UTC, datetime

import pytest

from jobpilot.classify.llm_classifier import (
    LLMClassifier,
    resolve_relative_deadline,
)
from jobpilot.llm.client import FakeLLMClient


@pytest.mark.asyncio
async def test_successful_oa_classification() -> None:
    """Verify successful parsing and extraction of an OA email."""
    canned_payload = {
        "label": "oa",
        "confidence": 0.95,
        "company": "Waymo",
        "role_title": "Software Engineer Intern",
        "platform": "HackerRank",
        "deadline_iso": "2026-10-15T23:59:59+00:00",
        "link": "https://hackerrank.com/tests/waymo-123",
    }
    fake_llm = FakeLLMClient(canned_responses=[json.dumps(canned_payload)])
    classifier = LLMClassifier(client=fake_llm)

    received_at = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    result = await classifier.classify(
        sender_domain="hackerrank.com",
        subject="Waymo Coding Assessment",
        body_snippet="Please complete the 90-minute assessment within 7 days.",
        received_at=received_at,
    )

    assert result.label == "oa"
    assert result.confidence == 0.95
    assert result.company == "Waymo"
    assert result.platform == "HackerRank"
    assert result.link == "https://hackerrank.com/tests/waymo-123"
    assert result.deadline_iso is not None


@pytest.mark.asyncio
async def test_low_confidence_fallback_to_other() -> None:
    """Verify that predictions with confidence < 0.7 fallback to 'other'."""
    canned_payload = {
        "label": "interview",
        "confidence": 0.65,  # Below 0.7 threshold
        "company": "Unknown Corp",
        "role_title": "Engineer",
        "platform": None,
        "deadline_iso": None,
        "link": None,
    }
    fake_llm = FakeLLMClient(canned_responses=[json.dumps(canned_payload)])
    classifier = LLMClassifier(client=fake_llm)

    received_at = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    result = await classifier.classify(
        sender_domain="unknown.com",
        subject="Quick question",
        body_snippet="Are you free for a call?",
        received_at=received_at,
    )

    assert result.label == "other"
    assert result.confidence == 0.65


@pytest.mark.asyncio
async def test_retry_on_invalid_json() -> None:
    """Verify that classifier retries once when receiving malformed JSON."""
    invalid_json = "This is not valid json at all"
    valid_json = json.dumps(
        {
            "label": "interview",
            "confidence": 0.9,
            "company": "Aurora",
            "role_title": "Software Engineer",
            "platform": "Calendly",
            "deadline_iso": None,
            "link": "https://calendly.com/aurora",
        }
    )

    fake_llm = FakeLLMClient(canned_responses=[invalid_json, valid_json])
    classifier = LLMClassifier(client=fake_llm)

    received_at = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    result = await classifier.classify(
        sender_domain="greenhouse.io",
        subject="Interview with Aurora",
        body_snippet="Schedule your technical screen.",
        received_at=received_at,
    )

    assert result.label == "interview"
    assert result.company == "Aurora"
    assert len(fake_llm.history) == 2


def test_relative_deadline_resolution() -> None:
    """Verify parsing relative timeframe descriptions against received_at."""
    base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)

    # 7 days
    d1 = resolve_relative_deadline("within 7 days", base_time)
    assert d1 == datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)

    # 48 hours
    d2 = resolve_relative_deadline("in 48 hours", base_time)
    assert d2 == datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)

    # 2 weeks
    d3 = resolve_relative_deadline("2 weeks from today", base_time)
    assert d3 == datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
