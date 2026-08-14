"""Thin LLM provider seam.

One method: (system, user) -> text. Keeping the surface this small makes
the provider swappable via env (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY)
and lets tests substitute a deterministic fake without any SDK mocking.

Determinism note: current Claude models accept no sampling parameters
(sending temperature is an API error), so best-effort stability comes
from the pinned model id and word-band confidences. For local
Anthropic-compatible servers, which do honor sampling, temperature is
pinned to 0.
"""

from typing import Protocol

import anthropic


class LLMError(Exception):
    """The LLM provider failed or returned something unusable."""


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    """Anthropic Messages API — or anything speaking it.

    base_url makes this client point at any Anthropic-compatible server
    (e.g. LM Studio's local /v1/messages endpoint), in which case the
    api_key can be a placeholder.
    """

    def __init__(self, model: str, api_key: str | None, base_url: str | None = None):
        if not api_key and not base_url:
            raise LLMError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set")
        self._model = model
        # Current Claude models reject sampling parameters entirely; local
        # Anthropic-compatible servers (LM Studio etc.) still honor
        # temperature, where 0 helps determinism.
        self._extra = {"temperature": 0} if base_url else {}
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or "local-server", base_url=base_url
        )

    async def complete(self, system: str, user: str) -> str:
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
                **self._extra,
            )
        except anthropic.AnthropicError as exc:
            raise LLMError(f"LLM provider error: {exc}") from exc
        parts = [block.text for block in resp.content if block.type == "text"]
        if not parts:
            raise LLMError("LLM returned no text content")
        return "".join(parts)


def make_llm_client(
    provider: str, model: str, api_key: str | None, base_url: str | None = None
) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(model=model, api_key=api_key, base_url=base_url)
    raise LLMError(f"unknown LLM provider: {provider!r}")
