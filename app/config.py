"""Configuration — everything comes from environment variables.

The brief requires the container to start clean from env alone: no
hard-coded hosts, models, or keys. EVALUATOR_VERSION is part of the
determinism key (request + catalog version + evaluator version => answer).
"""

import os
from dataclasses import dataclass

EVALUATOR_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    catalog_base: str
    llm_provider: str
    llm_model: str
    llm_api_key: str | None
    llm_base_url: str | None
    catalog_timeout_s: float
    llm_max_concurrency: int


def load_settings() -> Settings:
    return Settings(
        catalog_base=os.environ.get("CATALOG_BASE", "http://127.0.0.1:9001"),
        llm_provider=os.environ.get("LLM_PROVIDER", "anthropic"),
        llm_model=os.environ.get("LLM_MODEL", "claude-sonnet-5"),
        llm_api_key=os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
        llm_base_url=os.environ.get("LLM_BASE_URL"),
        catalog_timeout_s=float(os.environ.get("CATALOG_TIMEOUT_S", "5")),
        llm_max_concurrency=int(os.environ.get("LLM_MAX_CONCURRENCY", "4")),
    )
