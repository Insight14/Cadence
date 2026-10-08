"""Greenhouse job board API adapter."""

import logging
from datetime import datetime

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


class GreenhouseAdapter(BaseJobBoardAdapter):
    """Fetches and normalizes job postings from Greenhouse public boards API."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

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
                params={"content": "true"},
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
                raise JobBoardNotFoundError(f"Greenhouse board '{board_token}' not found.")

            if response.status_code == 429:
                raise JobBoardRateLimitError(f"Rate limited by Greenhouse API for '{board_token}'.")

            if response.is_error:
                raise JobBoardError(
                    f"Greenhouse API returned error HTTP {response.status_code} for '{board_token}'"
                )

            data = response.json()
            jobs_list = data.get("jobs", [])
            normalized_jobs: list[NormalizedJob] = []

            for item in jobs_list:
                ext_id = str(item.get("id", ""))
                title = item.get("title", "").strip()
                if not ext_id or not title:
                    continue

                location_dict = item.get("location")
                location_name = (
                    location_dict.get("name") if isinstance(location_dict, dict) else None
                )

                raw_content = item.get("content")
                description_text = clean_html_to_text(raw_content)

                updated_at_raw = item.get("updated_at")
                updated_at_dt: datetime | None = None
                if updated_at_raw:
                    try:
                        updated_at_dt = datetime.fromisoformat(updated_at_raw)
                    except (ValueError, TypeError):
                        pass

                is_target = is_student_or_new_grad_role(
                    title=title,
                    description_text=description_text,
                )

                job = NormalizedJob(
                    external_id=ext_id,
                    title=title,
                    location=location_name,
                    url=item.get("absolute_url")
                    or f"https://boards.greenhouse.io/{board_token}/jobs/{ext_id}",
                    description_text=description_text,
                    is_internship_or_grad=is_target,
                    updated_at_remote=updated_at_dt,
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
            raise JobBoardError(f"Network error communicating with Greenhouse: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()
