"""Job board polling and diffing engine."""

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import Company, JobPosting
from jobpilot.jobs.normalize import NormalizedJob
from jobpilot.jobs.sources import (
    JobBoardError,
    JobBoardNotFoundError,
    JobBoardRateLimitError,
    get_adapter,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollCompanyResult:
    """Summary metrics of polling a single company's career board."""

    company_id: uuid.UUID
    company_name: str
    ats: str
    new_jobs_count: int
    updated_jobs_count: int
    closed_jobs_count: int
    total_open_count: int
    duration_ms: float
    error: str | None = None


class JobBoardPoller:
    """Polls ATS boards for monitored companies and syncs job postings with diffing."""

    def __init__(self, request_timeout: float = 20.0) -> None:
        self.request_timeout = request_timeout

    async def poll_company(
        self,
        session: AsyncSession,
        company: Company,
        client: httpx.AsyncClient | None = None,
    ) -> PollCompanyResult:
        """Poll a single company's board, diff with DB state, and persist updates."""
        start_time = time.monotonic()
        now = datetime.now(UTC)

        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.request_timeout)
            close_client = True

        try:
            adapter = get_adapter(company.ats)
        except ValueError as err:
            logger.warning("Unsupported ATS for company %s: %s", company.name, err)
            return PollCompanyResult(
                company_id=company.id,
                company_name=company.name,
                ats=company.ats,
                new_jobs_count=0,
                updated_jobs_count=0,
                closed_jobs_count=0,
                total_open_count=0,
                duration_ms=(time.monotonic() - start_time) * 1000.0,
                error=str(err),
            )

        try:
            fetch_result = await adapter.fetch_jobs(
                board_token=company.board_token,
                client=client,
            )
        except JobBoardNotFoundError as err:
            logger.warning(
                "Company board not found for %s (%s): %s",
                company.name,
                company.ats,
                err,
            )
            return PollCompanyResult(
                company_id=company.id,
                company_name=company.name,
                ats=company.ats,
                new_jobs_count=0,
                updated_jobs_count=0,
                closed_jobs_count=0,
                total_open_count=0,
                duration_ms=(time.monotonic() - start_time) * 1000.0,
                error=str(err),
            )
        except (JobBoardRateLimitError, JobBoardError) as err:
            logger.error("Error polling company board %s: %s", company.name, err)
            return PollCompanyResult(
                company_id=company.id,
                company_name=company.name,
                ats=company.ats,
                new_jobs_count=0,
                updated_jobs_count=0,
                closed_jobs_count=0,
                total_open_count=0,
                duration_ms=(time.monotonic() - start_time) * 1000.0,
                error=str(err),
            )
        finally:
            if close_client:
                await client.aclose()

        if fetch_result.not_modified:
            logger.debug("Board %s not modified (304)", company.name)
            return PollCompanyResult(
                company_id=company.id,
                company_name=company.name,
                ats=company.ats,
                new_jobs_count=0,
                updated_jobs_count=0,
                closed_jobs_count=0,
                total_open_count=0,
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        remote_jobs = fetch_result.jobs
        remote_jobs_map: dict[str, NormalizedJob] = {j.external_id: j for j in remote_jobs}

        # Query existing job postings for this company
        stmt = select(JobPosting).where(JobPosting.company_id == company.id)
        result = await session.scalars(stmt)
        existing_postings: dict[str, JobPosting] = {p.external_id: p for p in result.all()}

        new_count = 0
        updated_count = 0
        closed_count = 0

        # 1. Process remote jobs (new + updated)
        for ext_id, r_job in remote_jobs_map.items():
            if ext_id not in existing_postings:
                # New posting
                new_posting = JobPosting(
                    company_id=company.id,
                    external_id=ext_id,
                    title=r_job.title,
                    location=r_job.location,
                    url=r_job.url,
                    description_text=r_job.description_text,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_open=True,
                )
                session.add(new_posting)
                new_count += 1
                logger.info(
                    "Detected new job posting: [%s] %s (%s)",
                    company.name,
                    r_job.title,
                    ext_id,
                )
            else:
                existing = existing_postings[ext_id]
                existing.last_seen_at = now

                # Reopened
                if not existing.is_open:
                    existing.is_open = True
                    updated_count += 1
                    logger.info(
                        "Job posting reopened: [%s] %s (%s)",
                        company.name,
                        existing.title,
                        ext_id,
                    )
                # Updated fields
                if (
                    existing.title != r_job.title
                    or existing.location != r_job.location
                    or existing.url != r_job.url
                ):
                    existing.title = r_job.title
                    existing.location = r_job.location
                    existing.url = r_job.url
                    if r_job.description_text:
                        existing.description_text = r_job.description_text
                    updated_count += 1

        # 2. Process disappeared jobs (mark is_open = False)
        for ext_id, existing in existing_postings.items():
            if ext_id not in remote_jobs_map and existing.is_open:
                existing.is_open = False
                closed_count += 1
                logger.info(
                    "Job posting closed/removed: [%s] %s (%s)",
                    company.name,
                    existing.title,
                    ext_id,
                )

        await session.commit()

        duration_ms = (time.monotonic() - start_time) * 1000.0
        total_open = sum(1 for p in existing_postings.values() if p.is_open) + new_count

        logger.info(
            "Polled %s (%s): %d new, %d updated, %d closed in %.2fms (total open: %d)",
            company.name,
            company.ats,
            new_count,
            updated_count,
            closed_count,
            duration_ms,
            total_open,
        )

        return PollCompanyResult(
            company_id=company.id,
            company_name=company.name,
            ats=company.ats,
            new_jobs_count=new_count,
            updated_jobs_count=updated_count,
            closed_jobs_count=closed_count,
            total_open_count=total_open,
            duration_ms=duration_ms,
        )

    async def poll_all_companies(
        self,
        session: AsyncSession,
        delay_between_requests: float = 0.5,
    ) -> list[PollCompanyResult]:
        """Poll all monitored companies registered in the database."""
        stmt = select(Company).order_by(Company.name)
        result = await session.scalars(stmt)
        companies = list(result.all())

        if not companies:
            logger.info("No companies registered to poll.")
            return []

        logger.info("Starting job board poll for %d companies", len(companies))
        results: list[PollCompanyResult] = []

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            for idx, company in enumerate(companies):
                res = await self.poll_company(session, company, client=client)
                results.append(res)

                # Polite pacing with jitter
                if idx < len(companies) - 1 and delay_between_requests > 0:
                    jitter = random.uniform(0.8, 1.2) * delay_between_requests
                    await asyncio.sleep(jitter)

        total_new = sum(r.new_jobs_count for r in results)
        total_updated = sum(r.updated_jobs_count for r in results)
        total_closed = sum(r.closed_jobs_count for r in results)
        logger.info(
            "Completed job board poll: %d new, %d updated, %d closed across %d companies",
            total_new,
            total_updated,
            total_closed,
            len(companies),
        )
        return results
