"""Abstract base adapter for job board scrapers."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from jobpilot.jobs.normalize import NormalizedJob

logger = logging.getLogger(__name__)


class JobBoardError(Exception):
    """Base exception for job board polling errors."""

    pass


class JobBoardNotFoundError(JobBoardError):
    """Board token or organization not found (404)."""

    pass


class JobBoardRateLimitError(JobBoardError):
    """Rate limited (429)."""

    pass


class JobBoardNotModified(JobBoardError):
    """HTTP 304 Not Modified when ETag or If-Modified-Since matches."""

    pass


@dataclass(frozen=True)
class FetchResult:
    """Result of fetching jobs from a career board."""

    jobs: list[NormalizedJob]
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class BaseJobBoardAdapter(ABC):
    """Abstract base class for company career board APIs."""

    @abstractmethod
    async def fetch_jobs(
        self,
        board_token: str,
        client: httpx.AsyncClient | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """Fetch and normalize job postings for a given board token."""
        pass
