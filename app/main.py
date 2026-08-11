"""HTTP surface of the Evaluator.

Endpoints:
  GET  /health      liveness probe
  GET  /version     evaluator build version (part of the determinism key)
  POST /v1/evaluate (added in a later step)
"""

from fastapi import FastAPI

from app.config import EVALUATOR_VERSION, Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Site Capability Evaluator", version=EVALUATOR_VERSION)
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict:
        return {"evaluatorVersion": EVALUATOR_VERSION}

    return app


app = create_app()
