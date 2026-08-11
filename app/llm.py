"""Thin LLM provider seam.

One method: (system, user) -> text. Keeping the surface this small makes
the provider swappable via env (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY)
and lets tests substitute a deterministic fake without any SDK mocking.
Temperature is pinned to 0 everywhere — part of the determinism story.
"""

from typing import Protocol

import anthropic


class LLMError(Exception):
    """The LLM provider failed or returned something unusable."""


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self, model: str, api_key: str | None):
        if not api_key:
            raise LLMError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set")
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str) -> str:
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AnthropicError as exc:
            raise LLMError(f"LLM provider error: {exc}") from exc
        parts = [block.text for block in resp.content if block.type == "text"]
        if not parts:
            raise LLMError("LLM returned no text content")
        return "".join(parts)


def make_llm_client(provider: str, model: str, api_key: str | None) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(model=model, api_key=api_key)
    raise LLMError(f"unknown LLM provider: {provider!r}")
