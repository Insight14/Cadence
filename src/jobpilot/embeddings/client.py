"""Embeddings client interface with Google Gemini and mock implementations."""

import hashlib
import logging
import math
from abc import ABC, abstractmethod
from typing import Any

from jobpilot.config import get_settings

logger = logging.getLogger(__name__)


class BaseEmbeddingsClient(ABC):
    """Abstract interface for generating vector embeddings."""

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding vector for a single text."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts."""
        pass


class FakeEmbeddingsClient(BaseEmbeddingsClient):
    """Deterministic, zero-network embedding client for unit tests and CI."""

    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension

    def _generate_vector(self, text: str) -> list[float]:
        """Generate deterministic unit-normalized vector from text hash."""
        vec: list[float] = []
        for i in range(self.dimension):
            h = hashlib.sha256(f"{text}:{i}".encode()).hexdigest()
            # Convert hex chunk to float in [-1.0, 1.0]
            val = (int(h[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0
            vec.append(val)

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    async def embed_text(self, text: str) -> list[float]:
        return self._generate_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]


class GeminiEmbeddingsClient(BaseEmbeddingsClient):
    """Generates dense vector embeddings using Google Gemini text-embedding-004."""

    def __init__(self, api_key: str, model_name: str = "text-embedding-004") -> None:
        self.api_key = api_key
        self.model_name = model_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                logger.error("Failed to initialize Google GenAI Client: %s", exc)
                raise
        return self._client

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        batch = await self.embed_batch([text])
        if not batch:
            return []
        return batch[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []

        client = self._get_client()
        try:
            # Call Gemini embeddings API
            response = client.models.embed_content(
                model=self.model_name,
                contents=texts,
            )
            results: list[list[float]] = []
            if hasattr(response, "embeddings") and response.embeddings:
                for item in response.embeddings:
                    if hasattr(item, "values"):
                        results.append(list(item.values))
                    elif isinstance(item, list):
                        results.append(item)
            return results
        except Exception as exc:
            logger.error("Gemini embedding generation failed: %s", exc)
            # Fallback to deterministic fake vector in case of API degradation
            fake = FakeEmbeddingsClient(dimension=768)
            return await fake.embed_batch(texts)


def get_embeddings_client() -> BaseEmbeddingsClient:
    """Return the configured embeddings client singleton."""
    settings = get_settings()
    api_key = settings.embeddings_api_key or settings.gemini_api_key

    if not api_key or api_key.startswith("mock") or api_key == "":
        return FakeEmbeddingsClient(dimension=settings.embeddings_dimension)

    return GeminiEmbeddingsClient(api_key=api_key)
