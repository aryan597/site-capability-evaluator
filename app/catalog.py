"""Catalog client: fetch over HTTP, cache by version.

Cache semantics follow from the catalog's immutability guarantee:
  - a pinned version, once fetched, is cached forever (identical content);
  - "latest" is a moving pointer, so it is re-fetched on every unpinned
    request, but the result is stored under its actual version, and the
    last-known-latest is served as a fallback if the catalog API is down.
"""

from typing import Literal

import httpx
from pydantic import BaseModel

Criticality = Literal["must", "should", "nice"]
Level = Literal[0, 1, 2, 3]

_CRITICALITY_RANK = {"nice": 0, "should": 1, "must": 2}


def strictest(a: Criticality, b: Criticality) -> Criticality:
    return a if _CRITICALITY_RANK[a] >= _CRITICALITY_RANK[b] else b


class Requirement(BaseModel):
    capabilityId: str
    minLevel: Level
    criticality: Criticality


class Feature(BaseModel):
    id: str
    name: str
    question: str
    clusterId: str
    requires: list[Requirement]


class AcceptanceCriterion(BaseModel):
    level: Level
    text: str


class Capability(BaseModel):
    id: str
    name: str
    description: str
    areaId: str
    acceptanceCriteria: list[AcceptanceCriterion]


class ArchetypeFeature(BaseModel):
    featureId: str
    criticality: Criticality


class Archetype(BaseModel):
    id: str
    name: str
    description: str
    features: list[ArchetypeFeature]


class FeatureCluster(BaseModel):
    id: str
    name: str


class Catalog(BaseModel):
    version: str
    featureClusters: list[FeatureCluster]
    features: list[Feature]
    capabilities: list[Capability]
    archetypes: list[Archetype]
    investmentAreas: list[dict]

    def features_by_id(self) -> dict[str, Feature]:
        return {f.id: f for f in self.features}

    def features_by_cluster(self) -> dict[str, list[Feature]]:
        grouped: dict[str, list[Feature]] = {c.id: [] for c in self.featureClusters}
        for f in self.features:
            grouped.setdefault(f.clusterId, []).append(f)
        return grouped


class CatalogUnavailable(Exception):
    """Catalog API unreachable and no cached copy to fall back on."""


class CatalogVersionNotFound(Exception):
    """A pinned catalog version does not exist (API returned 404)."""


class CatalogClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport
        self._cache: dict[str, Catalog] = {}
        self._latest_version: str | None = None

    async def get(self, version: str | None = None) -> Catalog:
        if version is not None:
            if version in self._cache:
                return self._cache[version]
            catalog = await self._fetch(version)
            self._cache[catalog.version] = catalog
            return catalog

        # Unpinned: "latest" can move, so always try the API first and
        # fall back to the last-known-latest only if the API is down.
        try:
            catalog = await self._fetch(None)
        except CatalogUnavailable:
            if self._latest_version and self._latest_version in self._cache:
                return self._cache[self._latest_version]
            raise
        self._cache[catalog.version] = catalog
        self._latest_version = catalog.version
        return catalog

    async def _fetch(self, version: str | None) -> Catalog:
        params = {"version": version} if version else None
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s, transport=self._transport
            ) as client:
                resp = await client.get(f"{self._base_url}/v1/catalog", params=params)
        except httpx.HTTPError as exc:
            raise CatalogUnavailable(f"catalog API unreachable: {exc}") from exc
        if resp.status_code == 404:
            raise CatalogVersionNotFound(version or "latest")
        if resp.status_code != 200:
            raise CatalogUnavailable(f"catalog API returned {resp.status_code}")
        return Catalog.model_validate(resp.json())
