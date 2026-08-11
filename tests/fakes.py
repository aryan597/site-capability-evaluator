"""Shared test fakes: a scripted LLM and a catalog API transport."""

import json
import re
from pathlib import Path

import httpx

from app.catalog import CatalogClient

ROOT = Path(__file__).resolve().parent.parent
CATALOG_JSON = json.loads((ROOT / "fixtures" / "catalog.json").read_text(encoding="utf-8"))
CATALOG_VERSION = CATALOG_JSON["version"]


class ScriptedLLM:
    """Fake LLM: returns a canned reply per cluster (parsed from the prompt)."""

    def __init__(self, replies_by_cluster: dict[str, str]):
        self._replies = replies_by_cluster
        self.calls: list[str] = []

    async def complete(self, system: str, user: str) -> str:
        cluster = re.match(r"Feature cluster: (.+)", user).group(1)
        self.calls.append(cluster)
        return self._replies[cluster]


def verdict_json(*items) -> str:
    return json.dumps({"features": list(items)})


def verdict(feature_id: str, present: bool, confidence: str = "high", evidence: str = "test") -> dict:
    return {"featureId": feature_id, "present": present,
            "confidence": confidence, "evidence": evidence}


def fixture_catalog_client() -> CatalogClient:
    def handler(request: httpx.Request) -> httpx.Response:
        version = request.url.params.get("version")
        if version and version != CATALOG_VERSION:
            return httpx.Response(404)
        return httpx.Response(200, json=CATALOG_JSON)

    return CatalogClient("http://catalog.test", transport=httpx.MockTransport(handler))
