"""Privacy-minimal Gmail Sent folder search for cold outreach detection."""

import logging

from googleapiclient.discovery import Resource

logger = logging.getLogger(__name__)


def check_prior_outreach(
    service: Resource,
    company_domains: list[str],
    days_back: int = 60,
) -> tuple[bool, str | None]:
    """Check if the user has sent emails to any of the company's domains within the last N days.

    Privacy-minimal: only queries message IDs/counts in Sent folder.
    Zero email bodies, subjects, or recipients are persisted or logged.

    Returns (has_sent_email, matching_domain).
    """
    if not company_domains:
        return False, None

    for domain in company_domains:
        clean_domain = domain.strip().lstrip("@").lower()
        if not clean_domain:
            continue

        query = f"to:{clean_domain} newer_than:{days_back}d"
        try:
            response = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=5,
                )
                .execute()
            )
            messages = response.get("messages", [])
            if messages:
                logger.info(
                    "Detected %d existing sent message(s) for domain %s (outreach already sent)",
                    len(messages),
                    clean_domain,
                )
                return True, clean_domain
        except Exception as exc:
            logger.warning("Error checking Sent messages for domain %s: %s", clean_domain, exc)

    return False, None
