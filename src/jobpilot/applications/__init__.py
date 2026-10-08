"""Applications module for tracking jobs, Sent searches, and cold email outreach."""

from jobpilot.applications.drafter import ColdEmailDraft, ColdEmailDrafter
from jobpilot.applications.nudge import (
    build_linkedin_hiring_manager_search_url,
    build_linkedin_recruiter_search_url,
)
from jobpilot.applications.tracker import ApplicationTracker

__all__ = [
    "ApplicationTracker",
    "ColdEmailDraft",
    "ColdEmailDrafter",
    "build_linkedin_hiring_manager_search_url",
    "build_linkedin_recruiter_search_url",
]
