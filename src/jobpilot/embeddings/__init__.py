"""Embeddings interface package."""

from jobpilot.embeddings.client import (
    BaseEmbeddingsClient,
    FakeEmbeddingsClient,
    GeminiEmbeddingsClient,
    get_embeddings_client,
)

__all__ = [
    "BaseEmbeddingsClient",
    "FakeEmbeddingsClient",
    "GeminiEmbeddingsClient",
    "get_embeddings_client",
]
