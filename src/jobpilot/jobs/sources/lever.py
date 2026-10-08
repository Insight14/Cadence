"""Lever job board API adapter."""

import logging
from datetime import UTC, datetime

import httpx

from jobpilot.jobs.normalize import (
    NormalizedJob,
    clean_html_to_text,
    is_student_or_new_grad_role,
)
from jobpilot.jobs.sources.base import (
    BaseJobBoardAdapter,
    FetchResult,
    JobBoardError,
    JobBoardNotFoundError,
    JobBoardRateLimitError,
)

logger = logging.getLogger(__name__)


class LeverAdapter(BaseJobBoardAdapter):
    """Fetches and normalizes job postings from Lever public postings API."""

    BASE_URL = "https://api.lever.co/v0/postings/{board_token}"

    async def fetch_jobs(
        self,
        board_token: str,
        client: httpx.AsyncClient | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        url = self.BASE_URL.format(board_token=board_token)
        headers: dict[str, str] = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            close_client = True

        try:
            response = await client.get(
                url,
                params={"mode": "json"},
                headers=headers,
            )

            if response.status_code == 304:
                return FetchResult(
                    jobs=[],
                    etag=etag,
                    last_modified=last_modified,
                    not_modified=True,
                )

            if response.status_code == 404:
                raise JobBoardNotFoundError(f"Lever board '{board_token}' not found.")

            if response.status_code == 429:
                raise JobBoardRateLimitError(f"Rate limited by Lever API for '{board_token}'.")

            if response.is_error:
                raise JobBoardError(
                    f"Lever API returned error HTTP {response.status_code} for '{board_token}'"
                )

            postings_list = response.json()
            if not isinstance(postings_list, list):
                postings_list = []

            normalized_jobs: list[NormalizedJob] = []

            for item in postings_list:
                ext_id = str(item.get("id", ""))
                title = item.get("text", "").strip()
                if not ext_id or not title:
                    continue

                categories = item.get("categories") or {}
                location_name = categories.get("location") if isinstance(categories, dict) else None

                description_text = item.get("descriptionPlain")
                if not description_text:
                    raw_desc = item.get("description")
                    description_text = clean_html_to_text(raw_desc)

                created_at_ms = item.get("createdAt")
                created_at_dt: datetime | None = None
                if created_at_ms and isinstance(created_at_ms, (int, float)):
                    created_at_dt = datetime.fromtimestamp(created_at_ms / 1000.0, tz=UTC)

                is_target = is_student_or_new_grad_role(
                    title=title,
                    description_text=description_text,
                )

                job = NormalizedJob(
                    external_id=ext_id,
                    title=title,
                    location=location_name,
                    url=item.get("hostedUrl") or f"https://jobs.lever.co/{board_token}/{ext_id}",
                    description_text=description_text,
                    is_internship_or_grad=is_target,
                    updated_at_remote=created_at_dt,
                )
                normalized_jobs.append(job)

            resp_etag = response.headers.get("etag")
            resp_last_modified = response.headers.get("last-modified")

            return FetchResult(
                jobs=normalized_jobs,
                etag=resp_etag,
                last_modified=resp_last_modified,
                not_modified=False,
            )

        except httpx.RequestError as exc:
            raise JobBoardError(f"Network error communicating with Lever: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()
