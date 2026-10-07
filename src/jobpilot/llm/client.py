"""LLM provider interfaces and implementations."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from jobpilot.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract interface for swappable LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate a completion from the LLM."""
        pass


class FakeLLMClient(LLMClient):
    """Mock LLM client for deterministic unit tests and offline evals."""

    def __init__(
        self, canned_responses: list[str] | None = None, default_response: str | None = None
    ) -> None:
        self.canned_responses: list[str] = list(canned_responses) if canned_responses else []
        self.default_response: str = default_response or json.dumps(
            {
                "label": "other",
                "confidence": 0.9,
                "company": None,
                "role_title": None,
                "platform": None,
                "deadline_iso": None,
                "link": None,
            }
        )
        self.history: list[dict[str, Any]] = []

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.history.append({"prompt": prompt, "system_prompt": system_prompt})
        if self.canned_responses:
            return self.canned_responses.pop(0)
        return self.default_response


class GeminiLLMClient(LLMClient):
    """Google Gemini LLM client using google-genai SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.llm_model
        if not self.api_key:
            logger.warning("GeminiLLMClient initialized without API key.")

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt if system_prompt else None,
            temperature=0.1,
            response_mime_type="application/json",
        )

        # Async call
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text or "{}"


class AnthropicLLMClient(LLMClient):
    """Anthropic Claude LLM client."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.llm_model

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key)
        system = system_prompt or "You are a precise data extraction assistant."
        message = await client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        first_block = message.content[0]
        if hasattr(first_block, "text"):
            return str(first_block.text)
        return "{}"


def get_llm_client() -> LLMClient:
    """Factory function returning the configured LLM client."""
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()
    if provider == "gemini":
        return GeminiLLMClient()
    elif provider == "anthropic":
        return AnthropicLLMClient()
    elif provider in ("fake", "mock", "test"):
        return FakeLLMClient()
    else:
        logger.warning("Unrecognized LLM provider %s, defaulting to Gemini", provider)
        return GeminiLLMClient()
