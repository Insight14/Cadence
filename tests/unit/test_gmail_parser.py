"""Unit tests for in-memory Gmail message parser."""

import base64
from datetime import UTC

from jobpilot.gmail.parser import (
    extract_domain,
    parse_email_metadata,
    parse_full_email,
    parse_internal_date,
)


def test_extract_domain() -> None:
    """Verify domain extraction from various From header formats."""
    assert extract_domain("Recruiting <jobs@waymo.com>") == "waymo.com"
    assert extract_domain("hiring@lever.co") == "lever.co"
    assert extract_domain("notifications@sub.company.org") == "sub.company.org"
    assert extract_domain("plain_invalid_string") is None


def test_parse_internal_date() -> None:
    """Verify parsing epoch milliseconds to UTC datetime."""
    # 1760000000000 ms -> 2025-10-09 08:53:20 UTC
    dt = parse_internal_date("1760000000000")
    assert dt.tzinfo == UTC
    assert dt.year >= 2025


def test_parse_email_metadata_and_full_body() -> None:
    """Verify parsing Gmail API message dictionary structure."""
    raw_body_text = "Please complete your HackerRank assessment for Uber."
    encoded_body = base64.urlsafe_b64encode(raw_body_text.encode("utf-8")).decode("ASCII")

    message_dict = {
        "id": "msg_12345",
        "threadId": "thread_67890",
        "snippet": "Please complete your HackerRank...",
        "internalDate": "1760000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Uber Talent <recruiting@uber.com>"},
                {"name": "Subject", "value": "Uber Coding Challenge"},
                {"name": "Date", "value": "Thu, 9 Oct 2025 08:53:20 +0000"},
            ],
            "body": {
                "data": encoded_body,
            },
        },
    }

    # Test metadata
    meta = parse_email_metadata(message_dict)
    assert meta.message_id == "msg_12345"
    assert meta.thread_id == "thread_67890"
    assert meta.sender_domain == "uber.com"
    assert meta.subject == "Uber Coding Challenge"

    # Test full
    full = parse_full_email(message_dict)
    assert full.body_text == raw_body_text
    assert full.message_id == "msg_12345"
