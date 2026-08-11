"""Request/response models for POST /v1/evaluate — mirrors the brief's shapes.

Security note: Access/Credentials exist so the request parses, but they are
secrets. They are never logged, never cached, never echoed in responses or
trace, and simply go out of scope at end of request (no persistence exists).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.catalog import Criticality

SourceType = Literal["app", "marketing", "pricing", "docs", "login", "signup", "external", "other"]


class Site(BaseModel):
    domain: str = Field(min_length=1)
    name: str | None = None
    archetypeHint: str | None = None


class Page(BaseModel):
    url: str
    sourceType: SourceType
    text: str | None = None
    html: str | None = None
    title: str | None = None
    httpStatus: int | None = None
    notes: str | None = None


class Content(BaseModel):
    pages: list[Page]
    extraSignals: dict = Field(default_factory=dict)


class Credentials(BaseModel):
    username: str | None = None
    password: str | None = None
    secrets: dict[str, str] = Field(default_factory=dict)


class SessionCookie(BaseModel):
    name: str
    value: str
    domain: str


class Access(BaseModel):
    loginUrl: str | None = None
    credentials: Credentials | None = None
    sessionCookies: list[SessionCookie] = Field(default_factory=list)
    notes: str | None = None


class LiveCrawlOptions(BaseModel):
    enabled: bool = False
    maxPages: int | None = None
    timeBudgetMs: int | None = None


class Options(BaseModel):
    liveCrawl: LiveCrawlOptions | None = None
    model: str | None = None
    debug: bool = False


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Site
    content: Content | None = None
    access: Access | None = None
    options: Options | None = None
    catalogVersion: str | None = None


# --- response -------------------------------------------------------------

class ArchetypeOut(BaseModel):
    id: str
    confidence: float


class InferredFeatureOut(BaseModel):
    featureId: str
    present: bool
    criticality: Criticality
    confidence: float
    evidence: str


class RequiredCapabilityOut(BaseModel):
    capabilityId: str
    minLevel: int
    criticality: Criticality
    confidence: float
    sourceFeatureIds: list[str]
    reasoning: str


class EvidenceSource(BaseModel):
    type: str
    url: str | None = None
    used: bool
    note: str | None = None


class Investigation(BaseModel):
    mode: Literal["live", "passed-in", "mixed"]
    accessOutcome: Literal["authenticated", "public-only", "partial", "blocked"]
    evidenceSources: list[EvidenceSource]
    pagesUsed: int


class EvaluateResponse(BaseModel):
    catalogVersion: str
    evaluatorVersion: str
    archetype: ArchetypeOut
    inferredFeatures: list[InferredFeatureOut]
    requiredCapabilities: list[RequiredCapabilityOut]
    overallConfidence: float
    investigation: Investigation
    trace: dict | None = None


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
