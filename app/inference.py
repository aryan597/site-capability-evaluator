"""LLM feature inference — batched by cluster, run concurrently.

This is the only place the LLM is consulted, and the only question it is
asked is a judgment call: "which of this cluster's features does the site
have, on this page evidence?" Everything numeric happens in code:
the model reports confidence as a word from a fixed list, and we map
words to numbers. Prompt size stays bounded per cluster no matter how
large the catalog grows (~70 features => ~8-12 parallel calls).
"""

import asyncio
import json

from pydantic import BaseModel, ValidationError

from app.catalog import Catalog, Feature
from app.llm import LLMClient, LLMError

BAND_SCORES = {"certain": 0.95, "high": 0.85, "likely": 0.7, "unsure": 0.5, "weak": 0.3}

_MAX_PAGE_CHARS = 4000

SYSTEM_PROMPT = """\
You analyze captured pages from a company's website to determine which \
product features the site has. You are given page excerpts and a list of \
feature questions. For EVERY feature in the list you must return a verdict.

Rules:
- Judge ONLY from the provided pages. Never assume features the evidence \
does not support. Absence of evidence means present=false.
- Evidence vs speculation: a concretely named technology or visible \
structure supports an inference (a named payment provider implies its \
iframe), but a merely named-but-unshown page, step, or section does not \
(a wizard step labeled "Billing" is NOT evidence that card details are \
collected — its contents were never captured).
- "Surfaces worth testing" means the product itself, not its public \
shell. Marketing pages, login pages, and signup wizards are the shell — \
their reachability never makes a product "publicly reachable". If the \
pages indicate the product experience requires signing in (e.g. "log in \
to your dashboard"), answer public-reachability questions present=false, \
even though the shell pages themselves loaded without credentials. Only \
answer present=true if actual product surfaces (store, app screens, \
content) are usable without any login.
- evidence: one short sentence citing the page (by url or sourceType) and \
the concrete wording or structure that supports your verdict. For \
present=false, say what is missing.
- confidence is one of: certain, high, likely, unsure, weak. Use "certain" \
only for explicit on-page proof; use "likely" or below for inferences \
(e.g. a payment provider implies an iframe you cannot see directly).

Return ONLY a JSON object, no prose, exactly this shape:
{"features": [{"featureId": "...", "present": true, "confidence": "high", "evidence": "..."}]}"""


class PageEvidence(BaseModel):
    url: str
    sourceType: str
    title: str | None = None
    text: str | None = None


class InferredFeature(BaseModel):
    featureId: str
    present: bool
    confidence: float
    evidence: str


class _RawVerdict(BaseModel):
    featureId: str
    present: bool
    confidence: str
    evidence: str = ""


def build_cluster_prompt(cluster_name: str, features: list[Feature], pages: list[PageEvidence]) -> str:
    lines = [f"Feature cluster: {cluster_name}", "", "FEATURES TO JUDGE:"]
    for f in features:
        lines.append(f"- featureId: {f.id}")
        lines.append(f"  question: {f.question}")
    lines.append("")
    lines.append("CAPTURED PAGES:")
    for p in pages:
        lines.append(f"--- url: {p.url} | sourceType: {p.sourceType} | title: {p.title or ''}")
        lines.append((p.text or "")[:_MAX_PAGE_CHARS])
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"no JSON object in LLM reply: {text[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"malformed JSON from LLM: {exc}") from exc


def _parse_verdicts(reply: str, features: list[Feature]) -> list[InferredFeature]:
    """Turn one cluster reply into verdicts for exactly that cluster's features.

    LLM output is untrusted input: unknown feature ids are dropped, missing
    features are filled in as absent/unsure, unknown confidence words fall
    back to 'unsure'.
    """
    data = _extract_json(reply)
    by_id: dict[str, _RawVerdict] = {}
    for item in data.get("features", []):
        try:
            verdict = _RawVerdict.model_validate(item)
        except ValidationError:
            continue
        by_id[verdict.featureId] = verdict

    results = []
    for f in features:
        raw = by_id.get(f.id)
        if raw is None:
            results.append(
                InferredFeature(
                    featureId=f.id, present=False, confidence=BAND_SCORES["unsure"],
                    evidence="Model returned no verdict; treated as absent.",
                )
            )
            continue
        results.append(
            InferredFeature(
                featureId=f.id,
                present=raw.present,
                confidence=BAND_SCORES.get(raw.confidence.lower().strip(), BAND_SCORES["unsure"]),
                evidence=raw.evidence.strip()[:300] or "No evidence given.",
            )
        )
    return results


async def infer_features(
    llm: LLMClient, catalog: Catalog, pages: list[PageEvidence], max_concurrency: int = 4
) -> list[InferredFeature]:
    clusters = catalog.features_by_cluster()
    cluster_names = {c.id: c.name for c in catalog.featureClusters}
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_cluster(cluster_id: str, features: list[Feature]) -> list[InferredFeature]:
        prompt = build_cluster_prompt(cluster_names.get(cluster_id, cluster_id), features, pages)
        async with semaphore:
            reply = await llm.complete(SYSTEM_PROMPT, prompt)
        return _parse_verdicts(reply, features)

    batches = await asyncio.gather(
        *(run_cluster(cid, feats) for cid, feats in sorted(clusters.items()) if feats)
    )
    return [verdict for batch in batches for verdict in batch]
