"""Unit tests for Stage 1 rule-based email filter."""

import pytest

from jobpilot.classify.rules import is_candidate_email


@pytest.mark.parametrize(
    ("domain", "subject", "snippet"),
    [
        ("hackerrank.com", "Coding Assessment Invitation", "Complete in 7 days"),
        ("codesignal.com", "General Coding Assessment", "Take the test"),
        ("hirevue.com", "Video Interview", "Please complete your interview"),
        ("greenhouse.io", "Application received", "Thanks for applying to Stripe"),
        ("lever.co", "Interview with Figma", "Let's schedule a call"),
        ("company.com", "Online assessment for Software Engineer", "Here is your test link"),
        ("recruiting.corp.com", "Invitation to technical screen", "Schedule 45 mins"),
        ("jobs.myworkday.com", "Candidate Status Update", "Your application has been received"),
    ],
)
def test_candidate_emails_pass_stage1(domain: str, subject: str, snippet: str) -> None:
    """Verify that legitimate job/interview/assessment emails pass Stage 1."""
    assert is_candidate_email(domain, subject, snippet) is True


@pytest.mark.parametrize(
    ("domain", "subject", "snippet"),
    [
        ("tldr.tech", "TLDR AI: Daily Newsletter", "Here are the top AI stories today"),
        ("marketing.uber.com", "50% off your next Uber Eats order", "Order now and save"),
        ("spotify.com", "Your Daily Mix is Ready", "Listen now on Spotify"),
        ("receipts.amazon.com", "Your Amazon.com order #12345", "Shipped with Prime"),
        ("newsletter.substack.com", "Weekly Engineering Blog", "Thoughts on software architecture"),
    ],
)
def test_noise_emails_fail_stage1(domain: str, subject: str, snippet: str) -> None:
    """Verify that non-job noise and newsletters fail Stage 1 and never hit LLM."""
    assert is_candidate_email(domain, subject, snippet) is False
