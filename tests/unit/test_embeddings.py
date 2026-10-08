"""Unit tests for embedding clients and vector utilities."""

import pytest

from jobpilot.embeddings.client import (
    FakeEmbeddingsClient,
)
from jobpilot.jobs.matcher import compute_cosine_similarity
from jobpilot.resume.extractor import StructuredResumeProfile
from jobpilot.resume.service import build_profile_embed_text


@pytest.mark.asyncio
async def test_fake_embeddings_client() -> None:
    client = FakeEmbeddingsClient(dimension=768)
    vec1 = await client.embed_text("Python Backend Engineer")
    vec2 = await client.embed_text("Python Backend Engineer")
    vec3 = await client.embed_text("Graphic Designer Artist")

    assert len(vec1) == 768
    # Deterministic for same input
    assert vec1 == vec2
    # Different inputs produce different vectors
    assert vec1 != vec3

    # Cosine similarity identical is ~1.0
    sim_identical = compute_cosine_similarity(vec1, vec2)
    assert pytest.approx(sim_identical, 0.001) == 1.0

    # Batch embedding
    batch = await client.embed_batch(["Text 1", "Text 2"])
    assert len(batch) == 2
    assert len(batch[0]) == 768


def test_build_profile_embed_text() -> None:
    profile = StructuredResumeProfile(
        skills=["Python", "FastAPI"],
        domains=["Backend", "Fintech"],
        project_themes=["High-frequency Order Matching"],
        target_roles=["Software Engineer Intern"],
        summary="CS student with passion for systems.",
    )
    embed_text = build_profile_embed_text(profile)
    assert "Skills: Python, FastAPI" in embed_text
    assert "Domains: Backend, Fintech" in embed_text
    assert "Target Roles: Software Engineer Intern" in embed_text


def test_compute_cosine_similarity_edge_cases() -> None:
    assert compute_cosine_similarity(None, [1.0, 0.0]) == 0.0
    assert compute_cosine_similarity([1.0, 0.0], None) == 0.0
    assert compute_cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.5]) == 0.0  # Mismatched dims
    assert compute_cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0  # Zero vector
