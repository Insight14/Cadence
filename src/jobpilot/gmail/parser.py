"""In-memory Gmail message parsing with privacy guarantees."""

import base64
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedEmailMetadata:
    """Lightweight metadata extracted from message headers without full body."""

    message_id: str
    thread_id: str | None
    sender: str
    sender_domain: str | None
    subject: str
    snippet: str
    received_at: datetime


@dataclass
class ParsedEmail(ParsedEmailMetadata):
    """Full parsed email with trimmed in-memory body text."""

    body_text: str


def extract_domain(email_address: str) -> str | None:
    """Extract domain part from an email address or header string."""
    _, address = parseaddr(email_address)
    if "@" in address:
        return address.split("@")[-1].lower().strip()
    # Fallback regex
    match = re.search(r"@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", email_address)
    if match:
        return match.group(1).lower().strip()
    return None


def parse_internal_date(internal_date_ms: str | int | None) -> datetime:
    """Parse Gmail internalDate (milliseconds since epoch) into timezone-aware UTC datetime."""
    if not internal_date_ms:
        return datetime.now(UTC)
    try:
        timestamp_sec = int(internal_date_ms) / 1000.0
        return datetime.fromtimestamp(timestamp_sec, tz=UTC)
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _decode_body_part(part_data: str | None) -> str:
    """Decode base64url encoded Gmail body part."""
    if not part_data:
        return ""
    try:
        decoded_bytes = base64.urlsafe_b64decode(part_data.encode("ASCII"))
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body_from_payload(payload: dict[str, Any]) -> str:
    """Recursively extract plain text or HTML text from message payload."""
    mime_type = payload.get("mimeType", "")
    body_dict = payload.get("body", {})
    body_data = body_dict.get("data")

    if mime_type == "text/plain" and body_data:
        return _decode_body_part(body_data)

    parts = payload.get("parts", [])
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in parts:
        part_mime = part.get("mimeType", "")
        part_body = part.get("body", {})
        part_data = part_body.get("data")

        if part_mime == "text/plain" and part_data:
            plain_parts.append(_decode_body_part(part_data))
        elif part_mime == "text/html" and part_data:
            html_parts.append(_decode_body_part(part_data))
        elif "parts" in part:
            nested_text = _extract_body_from_payload(part)
            if nested_text:
                plain_parts.append(nested_text)

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        # Simple HTML tag stripping for text extraction
        raw_html = "\n".join(html_parts)
        stripped = re.sub(r"<[^>]+>", " ", raw_html)
        return re.sub(r"\s+", " ", stripped).strip()

    if body_data:
        return _decode_body_part(body_data)

    return ""


def parse_email_metadata(message_dict: dict[str, Any]) -> ParsedEmailMetadata:
    """Extract metadata headers and snippet without decoding full body."""
    msg_id = message_dict.get("id", "")
    thread_id = message_dict.get("threadId")
    snippet = message_dict.get("snippet", "")
    received_at = parse_internal_date(message_dict.get("internalDate"))

    headers_list = message_dict.get("payload", {}).get("headers", [])
    headers: dict[str, str] = {
        h.get("name", "").lower(): h.get("value", "") for h in headers_list if "name" in h
    }

    sender = headers.get("from", "")
    sender_domain = extract_domain(sender)
    subject = headers.get("subject", "")

    return ParsedEmailMetadata(
        message_id=msg_id,
        thread_id=thread_id,
        sender=sender,
        sender_domain=sender_domain,
        subject=subject,
        snippet=snippet,
        received_at=received_at,
    )


def parse_full_email(message_dict: dict[str, Any]) -> ParsedEmail:
    """Parse complete email message in-memory (never logged or persisted)."""
    meta = parse_email_metadata(message_dict)
    payload = message_dict.get("payload", {})
    body_text = _extract_body_from_payload(payload)

    return ParsedEmail(
        message_id=meta.message_id,
        thread_id=meta.thread_id,
        sender=meta.sender,
        sender_domain=meta.sender_domain,
        subject=meta.subject,
        snippet=meta.snippet,
        received_at=meta.received_at,
        body_text=body_text[:2000],  # Truncate in memory
    )
