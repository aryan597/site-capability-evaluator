"""The evaluate pipeline. The LLM is consulted exactly once (feature
inference); every other step is deterministic code:

    pages -> [LLM] infer features -> choose archetype -> rollup ->
    confidences -> response

Confidence design (documented in README):
  - feature: LLM word-band mapped to a fixed number
  - capability: max of contributing present features ("as sure as our
    best reason")
  - overall: criticality-weighted mean (must=3/should=2/nice=1) times an
    access-quality factor, so weaker evidence visibly lowers the number.
"""

from app.archetype import choose_archetype, feature_criticality
from app.catalog import Catalog, CatalogClient
from app.config import EVALUATOR_VERSION, Settings
from app.inference import InferredFeature, PageEvidence, infer_features
from app.llm import LLMClient
from app.models import (
    ArchetypeOut,
    EvaluateRequest,
    EvaluateResponse,
    EvidenceSource,
    InferredFeatureOut,
    Investigation,
    RequiredCapabilityOut,
)
from app.rollup import rollup

_CRIT_WEIGHT = {"must": 3, "should": 2, "nice": 1}
_ACCESS_FACTOR = {"authenticated": 1.0, "partial": 0.9, "public-only": 0.85, "blocked": 0.6}


class LiveModeUnsupported(Exception):
    """Request had no passed-in content; live crawling is not built in v1."""


async def evaluate(
    request: EvaluateRequest,
    catalog_client: CatalogClient,
    llm: LLMClient,
    settings: Settings,
) -> EvaluateResponse:
    if request.content is None or not request.content.pages:
        raise LiveModeUnsupported(
            "live mode is not implemented in v1: provide content.pages (pass-in mode)"
        )

    catalog = await catalog_client.get(request.catalogVersion)

    pages = [
        PageEvidence(url=p.url, sourceType=p.sourceType, title=p.title, text=p.text or p.html)
        for p in request.content.pages
    ]
    usable = [p for p in pages if p.text]

    inferred = await infer_features(llm, catalog, usable, settings.llm_max_concurrency)
    present_ids = [f.featureId for f in inferred if f.present]

    archetype = choose_archetype(catalog, present_ids, request.site.archetypeHint)
    rolled = rollup(present_ids, catalog)

    feature_conf = {f.featureId: f.confidence for f in inferred}
    capabilities = [
        RequiredCapabilityOut(
            capabilityId=c.capabilityId,
            minLevel=c.minLevel,
            criticality=c.criticality,
            confidence=round(max(feature_conf[fid] for fid in c.sourceFeatureIds), 2),
            sourceFeatureIds=c.sourceFeatureIds,
            reasoning=c.reasoning,
        )
        for c in rolled
    ]

    access_outcome = (
        "authenticated"
        if request.content.extraSignals.get("authenticated") is True
        else "public-only"
    )

    features_out = _features_out(inferred, catalog, archetype.id)
    overall = _overall_confidence(capabilities, access_outcome)

    investigation = Investigation(
        mode="passed-in",
        accessOutcome=access_outcome,
        evidenceSources=[
            EvidenceSource(
                type=p.sourceType,
                url=p.url,
                used=bool(p.text),
                note=None if p.text else "no extractable text",
            )
            for p in pages
        ],
        pagesUsed=len(usable),
    )

    trace = None
    if request.options and request.options.debug:
        trace = {
            "clusters": len(catalog.featureClusters),
            "llmCallsMade": len(catalog.featureClusters),
            "presentFeatureIds": sorted(present_ids),
            "accessFactor": _ACCESS_FACTOR[access_outcome],
        }

    return EvaluateResponse(
        catalogVersion=catalog.version,
        evaluatorVersion=EVALUATOR_VERSION,
        archetype=ArchetypeOut(id=archetype.id, confidence=archetype.confidence),
        inferredFeatures=features_out,
        requiredCapabilities=capabilities,
        overallConfidence=overall,
        investigation=investigation,
        trace=trace,
    )


def _features_out(
    inferred: list[InferredFeature], catalog: Catalog, archetype_id: str
) -> list[InferredFeatureOut]:
    by_id = {f.featureId: f for f in inferred}
    return [
        InferredFeatureOut(
            featureId=f.id,
            present=by_id[f.id].present,
            criticality=feature_criticality(catalog, archetype_id, f.id),
            confidence=round(by_id[f.id].confidence, 2),
            evidence=by_id[f.id].evidence,
        )
        for f in catalog.features  # catalog order: deterministic output
    ]


def _overall_confidence(capabilities: list[RequiredCapabilityOut], access_outcome: str) -> float:
    if not capabilities:
        return round(0.3 * _ACCESS_FACTOR[access_outcome], 2)
    weight_total = sum(_CRIT_WEIGHT[c.criticality] for c in capabilities)
    weighted = sum(c.confidence * _CRIT_WEIGHT[c.criticality] for c in capabilities)
    return round((weighted / weight_total) * _ACCESS_FACTOR[access_outcome], 2)
