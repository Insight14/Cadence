"""Job normalization models, HTML cleaning, and student/new-grad role classification."""

import html
import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NormalizedJob:
    """Normalized representation of a job posting across various ATS sources."""

    external_id: str
    title: str
    location: str | None
    url: str
    description_text: str | None
    is_internship_or_grad: bool
    updated_at_remote: datetime | None = None


# Positive regex patterns for student, intern, and new-grad roles
_POSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(intern|internship|interns)\b", re.IGNORECASE),
    re.compile(r"\b(co-?op|cooperative education)\b", re.IGNORECASE),
    re.compile(r"\b(new grad|new-grad|new graduate|new grads)\b", re.IGNORECASE),
    re.compile(r"\b(university grad|university graduate|university recruiting)\b", re.IGNORECASE),
    re.compile(r"\b(college grad|fresh grad|fresh graduate)\b", re.IGNORECASE),
    re.compile(r"\b(early career|entry level|entry-level)\b", re.IGNORECASE),
    re.compile(r"\b(campus recruiting|campus hire|undergraduate|student)\b", re.IGNORECASE),
    re.compile(r"\b(associate|apprentice|apprenticeship|rotational program)\b", re.IGNORECASE),
    re.compile(
        r"\b(2025|2026|2027)\s+(graduate|grad|intern|internship|full-?time)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(summer|fall|spring|winter)\s+(2025|2026|2027)\b", re.IGNORECASE),
]

# Negative patterns that disqualify roles (e.g. senior/manager roles)
_NEGATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(sr\.?|senior|staff|principal|distinguished)\b", re.IGNORECASE),
    re.compile(r"\b(director|vp|vice president|head of|lead|architect)\b", re.IGNORECASE),
    re.compile(r"\b(manager|group lead)\b", re.IGNORECASE),
]


def clean_html_to_text(html_content: str | None) -> str | None:
    """Strip HTML tags and unescape HTML entities to produce clean plain text."""
    if not html_content:
        return None

    # Replace breaks and paragraphs with newlines
    text = re.sub(r"<(br|p|div|li)[^>]*>", "\n", html_content, flags=re.IGNORECASE)
    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities (&amp;, &lt;, &gt;, &#39;, &nbsp;, etc.)
    text = html.unescape(text)
    # Collapse multiple spaces and newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip() or None


def is_student_or_new_grad_role(title: str, description_text: str | None = None) -> bool:
    """Evaluate whether a job posting matches student/intern/new-grad target criteria.

    Prioritizes title analysis, and falls back to description text if title is ambiguous.
    """
    title_clean = title.strip()

    # 1. Check positive title match
    for pattern in _POSITIVE_PATTERNS:
        if pattern.search(title_clean):
            return True

    # 2. Check if title matches strong negative indicators
    for neg_pattern in _NEGATIVE_PATTERNS:
        if neg_pattern.search(title_clean):
            return False

    # 3. If description is provided, check if description has prominent student indicators
    if description_text:
        desc_snippet = description_text[:2000]
        # Check high-confidence student phrases in description
        for pattern in _POSITIVE_PATTERNS:
            if pattern.search(desc_snippet):
                return True

    return False
