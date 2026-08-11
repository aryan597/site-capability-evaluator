"""HTTP surface of the Evaluator.

Endpoints:
  GET  /health       liveness probe
  GET  /version      evaluator build version (part of the determinism key)
  POST /v1/evaluate  the one real endpoint

Error taxonomy (all bodies: {"error": {"code", "message"}}):
  422 VALIDATION_ERROR            request body doesn't match the schema
  400 CATALOG_VERSION_NOT_FOUND   pinned catalog version doesn't exist
  501 LIVE_MODE_NOT_IMPLEMENTED   no content.pages given (v1 is pass-in only)
  502 LLM_ERROR                   LLM provider failed or unusable output
  503 CATALOG_UNAVAILABLE         catalog API down and nothing cached

A gated site is NOT an error: it returns 200 with a weaker accessOutcome.
Secrets note: error paths below never include request contents — only our
own code/message strings — so credentials cannot leak through them.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.catalog import CatalogClient, CatalogUnavailable, CatalogVersionNotFound
from app.config import EVALUATOR_VERSION, Settings, load_settings
from app.evaluator import LiveModeUnsupported, evaluate
from app.llm import LLMClient, LLMError, make_llm_client
from app.models import ErrorResponse, EvaluateRequest, EvaluateResponse

_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Pinned catalog version does not exist (CATALOG_VERSION_NOT_FOUND)."},
    422: {"model": ErrorResponse, "description": "Request body does not match the schema (VALIDATION_ERROR)."},
    501: {"model": ErrorResponse, "description": "No content.pages given; live mode is not implemented in v1 (LIVE_MODE_NOT_IMPLEMENTED)."},
    502: {"model": ErrorResponse, "description": "LLM provider failed or returned unusable output (LLM_ERROR)."},
    503: {"model": ErrorResponse, "description": "Catalog API unreachable and nothing cached (CATALOG_UNAVAILABLE)."},
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(
    settings: Settings | None = None,
    catalog_client: CatalogClient | None = None,
    llm: LLMClient | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Site Capability Evaluator", version=EVALUATOR_VERSION)
    app.state.settings = settings
    app.state.catalog_client = catalog_client or CatalogClient(
        settings.catalog_base, timeout_s=settings.catalog_timeout_s
    )
    app.state.llm = llm  # real client is created lazily so /health works without a key

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict:
        return {"evaluatorVersion": EVALUATOR_VERSION}

    @app.post(
        "/v1/evaluate",
        response_model=EvaluateResponse,
        response_model_exclude_none=True,
        responses=_ERROR_RESPONSES,
        summary="Evaluate what testing a site would require",
        description=(
            "Pass-in mode: judge feature presence from the supplied pages, then "
            "derive required capabilities deterministically from the catalog. "
            "A gated site is NOT an error: it returns 200 with a weaker "
            "accessOutcome and lower confidence."
        ),
    )
    async def evaluate_endpoint(request: EvaluateRequest) -> EvaluateResponse:
        if app.state.llm is None:
            app.state.llm = make_llm_client(
                settings.llm_provider, settings.llm_model, settings.llm_api_key
            )
        return await evaluate(request, app.state.catalog_client, app.state.llm, settings)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # exc.errors() can echo request values; report only field locations.
        locations = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return _error(422, "VALIDATION_ERROR", f"invalid request at: {', '.join(locations)}")

    @app.exception_handler(CatalogVersionNotFound)
    async def on_bad_version(_: Request, exc: CatalogVersionNotFound) -> JSONResponse:
        return _error(400, "CATALOG_VERSION_NOT_FOUND", f"catalog version not found: {exc}")

    @app.exception_handler(CatalogUnavailable)
    async def on_catalog_down(_: Request, exc: CatalogUnavailable) -> JSONResponse:
        return _error(503, "CATALOG_UNAVAILABLE", str(exc))

    @app.exception_handler(LiveModeUnsupported)
    async def on_live_mode(_: Request, exc: LiveModeUnsupported) -> JSONResponse:
        return _error(501, "LIVE_MODE_NOT_IMPLEMENTED", str(exc))

    @app.exception_handler(LLMError)
    async def on_llm_error(_: Request, exc: LLMError) -> JSONResponse:
        return _error(502, "LLM_ERROR", str(exc))

    return app


app = create_app()
