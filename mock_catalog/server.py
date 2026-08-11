"""Mock Catalog API — stands in for the production catalog service.

Serves fixtures/catalog.json with the real API's semantics:

  GET /v1/catalog              -> latest version
  GET /v1/catalog?version=<v>  -> that exact version, or 404 (immutable versions)

Run:  uvicorn mock_catalog.server:app --port 9001
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

_DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "catalog.json"


def create_app(fixture_path: Path | None = None) -> FastAPI:
    path = fixture_path or Path(os.environ.get("CATALOG_FIXTURE", _DEFAULT_FIXTURE))
    catalog = json.loads(path.read_text(encoding="utf-8"))

    app = FastAPI(title="Mock Catalog API")

    @app.get("/v1/catalog")
    def get_catalog(version: str | None = Query(default=None)) -> dict:
        if version is not None and version != catalog["version"]:
            raise HTTPException(status_code=404, detail=f"unknown catalog version: {version}")
        return catalog

    return app


app = create_app()
