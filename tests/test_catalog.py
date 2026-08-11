import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.catalog import CatalogClient, CatalogUnavailable, CatalogVersionNotFound

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "catalog.json"
CATALOG_JSON = json.loads(FIXTURE.read_text(encoding="utf-8"))
VERSION = CATALOG_JSON["version"]


class CountingCatalogAPI:
    """Fake catalog API as an httpx transport: counts hits, can be 'down'."""

    def __init__(self):
        self.hits = 0
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.hits += 1
        version = request.url.params.get("version")
        if version and version != VERSION:
            return httpx.Response(404)
        return httpx.Response(200, json=CATALOG_JSON)

    def client(self) -> CatalogClient:
        return CatalogClient("http://catalog.test", transport=httpx.MockTransport(self.handler))


def test_fetches_latest():
    client = CountingCatalogAPI().client()
    catalog = asyncio.run(client.get())
    assert catalog.version == VERSION
    assert len(catalog.features) == 10
    assert len(catalog.capabilities) == 13


def test_pinned_version_is_cached_forever():
    api = CountingCatalogAPI()
    client = api.client()

    async def twice():
        await client.get(VERSION)
        await client.get(VERSION)

    asyncio.run(twice())
    assert api.hits == 1  # second call served from cache


def test_unknown_pinned_version_raises():
    client = CountingCatalogAPI().client()
    with pytest.raises(CatalogVersionNotFound):
        asyncio.run(client.get("1999-01-01T00:00:00Z"))


def test_latest_falls_back_to_cache_when_api_down():
    api = CountingCatalogAPI()
    client = api.client()

    async def scenario():
        first = await client.get()      # warm: remembers latest
        api.down = True
        second = await client.get()     # API down: serve last-known-latest
        return first, second

    first, second = asyncio.run(scenario())
    assert first.version == second.version == VERSION


def test_no_cache_and_api_down_raises():
    api = CountingCatalogAPI()
    api.down = True
    with pytest.raises(CatalogUnavailable):
        asyncio.run(api.client().get())
