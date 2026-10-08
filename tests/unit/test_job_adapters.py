"""Unit tests for Greenhouse, Lever, and Ashby job board adapters."""

import httpx
import pytest

from jobpilot.jobs.sources import (
    AshbyAdapter,
    GreenhouseAdapter,
    JobBoardNotFoundError,
    JobBoardRateLimitError,
    LeverAdapter,
    get_adapter,
)


@pytest.mark.asyncio
async def test_greenhouse_adapter_success() -> None:
    adapter = GreenhouseAdapter()
    sample_payload = {
        "jobs": [
            {
                "id": 12345,
                "title": "Software Engineering Intern",
                "location": {"name": "Mountain View, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/12345",
                "updated_at": "2026-10-01T12:00:00-07:00",
                "content": "<p>Build autonomous vehicles.</p>",
            },
            {
                "id": 67890,
                "title": "Senior Infrastructure Engineer",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": "https://boards.greenhouse.io/waymo/jobs/67890",
                "updated_at": "2026-10-02T12:00:00-07:00",
                "content": "<p>10+ years experience required.</p>",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "waymo" in str(request.url)
        return httpx.Response(
            200,
            json=sample_payload,
            headers={"etag": '"etag-gh-123"', "last-modified": "Wed, 01 Oct 2026 12:00:00 GMT"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await adapter.fetch_jobs("waymo", client=client)

    assert result.not_modified is False
    assert result.etag == '"etag-gh-123"'
    assert len(result.jobs) == 2

    intern_job = result.jobs[0]
    assert intern_job.external_id == "12345"
    assert intern_job.title == "Software Engineering Intern"
    assert intern_job.location == "Mountain View, CA"
    assert intern_job.is_internship_or_grad is True
    assert intern_job.description_text == "Build autonomous vehicles."

    senior_job = result.jobs[1]
    assert senior_job.is_internship_or_grad is False


@pytest.mark.asyncio
async def test_greenhouse_adapter_304_not_modified() -> None:
    adapter = GreenhouseAdapter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await adapter.fetch_jobs("waymo", client=client, etag='"old-etag"')

    assert result.not_modified is True
    assert len(result.jobs) == 0


@pytest.mark.asyncio
async def test_greenhouse_adapter_404_not_found() -> None:
    adapter = GreenhouseAdapter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JobBoardNotFoundError):
            await adapter.fetch_jobs("nonexistent_company_xyz", client=client)


@pytest.mark.asyncio
async def test_lever_adapter_success() -> None:
    adapter = LeverAdapter()
    sample_payload = [
        {
            "id": "lever-uuid-1",
            "text": "Frontend Engineer Co-op",
            "categories": {"location": "Boston, MA", "team": "Web"},
            "hostedUrl": "https://jobs.lever.co/spotify/lever-uuid-1",
            "createdAt": 1727800000000,
            "descriptionPlain": "Build web apps at scale.",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await adapter.fetch_jobs("spotify", client=client)

    assert result.not_modified is False
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.external_id == "lever-uuid-1"
    assert job.title == "Frontend Engineer Co-op"
    assert job.location == "Boston, MA"
    assert job.is_internship_or_grad is True


@pytest.mark.asyncio
async def test_lever_adapter_rate_limit() -> None:
    adapter = LeverAdapter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Too Many Requests"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JobBoardRateLimitError):
            await adapter.fetch_jobs("spotify", client=client)


@pytest.mark.asyncio
async def test_ashby_adapter_success() -> None:
    adapter = AshbyAdapter()
    sample_payload = {
        "apiVersion": "2024-05-01",
        "jobs": [
            {
                "id": "ashby-uuid-99",
                "title": "Machine Learning Intern (Fall 2026)",
                "location": "San Francisco, CA",
                "jobUrl": "https://jobs.ashbyhq.com/anthropic/ashby-uuid-99",
                "publishedAt": "2026-10-01T00:00:00.000Z",
                "descriptionPlain": "Research and safety engineering.",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await adapter.fetch_jobs("anthropic", client=client)

    assert result.not_modified is False
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.external_id == "ashby-uuid-99"
    assert job.title == "Machine Learning Intern (Fall 2026)"
    assert job.location == "San Francisco, CA"
    assert job.is_internship_or_grad is True


def test_get_adapter_factory() -> None:
    assert isinstance(get_adapter("greenhouse"), GreenhouseAdapter)
    assert isinstance(get_adapter("GREENHOUSE"), GreenhouseAdapter)
    assert isinstance(get_adapter("lever"), LeverAdapter)
    assert isinstance(get_adapter("ashby"), AshbyAdapter)

    with pytest.raises(ValueError, match="Unsupported ATS"):
        get_adapter("workday_custom")
