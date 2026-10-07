"""Stage 1 rule-based cheap keyword and sender domain filter."""

import re

# Known assessment platforms & ATS domains
KNOWN_DOMAINS = {
    # Assessment & Interview Platforms
    "hackerrank.com",
    "hackerrankforwork.com",
    "codesignal.com",
    "codility.com",
    "hirevue.com",
    "karat.com",
    "karat.io",
    "coderbyte.com",
    "testgorilla.com",
    "pymetrics.com",
    "shl.com",
    "mya.com",
    "ripplematch.com",
    # ATS Notification Domains
    "greenhouse.io",
    "gh.greenhouse.io",
    "mailer.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "myworkday.com",
    "myworkdayjobs.com",
    "workday.com",
    "icims.com",
    "smartrecruiters.com",
    "jobvite.com",
    "bamboohr.com",
    "taleo.net",
    "recruitee.com",
    "rippling-ats.com",
}

# Strong keywords in subject or snippet/headers
KEYWORD_PATTERNS = [
    r"\bonline\s+assessment\b",
    r"\bcoding\s+challenge\b",
    r"\bcoding\s+assessment\b",
    r"\bhackerrank\b",
    r"\bcodesignal\b",
    r"\bcodility\b",
    r"\bhirevue\b",
    r"\bkarat\b",
    r"\binterview\b",
    r"\bschedule\s+(your|an|the)?\s*interview\b",
    r"\bnext\s+steps?\b",
    r"\binvitation\s+to\b",
    r"\btechnical\s+screen\b",
    r"\bphone\s+screen\b",
    r"\bapplication\s+(received|status|confirmation|submitted)\b",
    r"\bthank\s+you\s+for\s+applying\b",
    r"\bthanks\s+for\s+applying\b",
    r"\bupdate\s+on\s+your\s+application\b",
    r"\bregret\s+to\s+inform\b",
    r"\bunfortunately\b",
    r"\bnot\s+moving\s+forward\b",
    r"\bother\s+candidates\b",
    r"\btake-home\s+(project|challenge|assignment)\b",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in KEYWORD_PATTERNS]


def is_candidate_email(
    sender_domain: str | None,
    subject: str | None,
    snippet: str | None = None,
) -> bool:
    """Evaluate whether an incoming email should pass Stage 1 and be forwarded to Stage 2 LLM.

    Returns False for noise/spam/unrelated newsletters without hitting the LLM.
    """
    if sender_domain:
        domain_clean = sender_domain.lower().strip()
        # Check direct domain match or subdomain match
        for known in KNOWN_DOMAINS:
            if domain_clean == known or domain_clean.endswith(f".{known}"):
                return True

    text_to_check = f"{subject or ''} {snippet or ''}"
    if not text_to_check.strip():
        return False

    for pattern in COMPILED_PATTERNS:
        if pattern.search(text_to_check):
            return True

    return False
