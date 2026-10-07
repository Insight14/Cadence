"""Gmail package initialization."""

from jobpilot.gmail.client import build_gmail_service
from jobpilot.gmail.parser import (
    ParsedEmail,
    ParsedEmailMetadata,
    extract_domain,
    parse_email_metadata,
    parse_full_email,
)
from jobpilot.gmail.poller import GmailPoller

__all__ = [
    "GmailPoller",
    "ParsedEmail",
    "ParsedEmailMetadata",
    "build_gmail_service",
    "extract_domain",
    "parse_email_metadata",
    "parse_full_email",
]
