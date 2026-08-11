"""Deterministic archetype scoring.

Once feature presence is known, archetype choice is a measurement, not a
judgment call. Score = harmonic mean (F1) of:
  - coverage: criticality-weighted share of the archetype's bundle that
    is present (does the site look like this archetype expects?), and
  - explanation: share of the present features the bundle accounts for
    (does the archetype account for what we actually found?).
Coverage alone fails: a small generic archetype whose bundle is a subset
of the present features scores a perfect 1.0. An archetypeHint from the
caller adds a small bonus — evidence, not an override.

The winning archetype's bundle also supplies the criticality carried
through to inferredFeatures; present features outside the bundle default
to "should" (documented judgment call).
"""

from pydantic import BaseModel

from app.catalog import Archetype, Catalog, Criticality

_WEIGHT = {"must": 3, "should": 2, "nice": 1}
_HINT_BONUS = 0.1


class ArchetypeChoice(BaseModel):
    id: str
    confidence: float


def score_archetype(archetype: Archetype, present: set[str]) -> float:
    total = sum(_WEIGHT[f.criticality] for f in archetype.features)
    if total == 0 or not present:
        return 0.0
    bundle_ids = {f.featureId for f in archetype.features}
    matched = sum(_WEIGHT[f.criticality] for f in archetype.features if f.featureId in present)
    coverage = matched / total
    explained = len(present & bundle_ids) / len(present)
    if coverage + explained == 0:
        return 0.0
    return 2 * coverage * explained / (coverage + explained)


def choose_archetype(
    catalog: Catalog, present_feature_ids: list[str], hint: str | None = None
) -> ArchetypeChoice:
    present = set(present_feature_ids)
    known_hint = hint if any(a.id == hint for a in catalog.archetypes) else None

    best_id, best_score = "", -1.0
    for archetype in sorted(catalog.archetypes, key=lambda a: a.id):
        score = score_archetype(archetype, present)
        if archetype.id == known_hint:
            score += _HINT_BONUS
        if score > best_score:
            best_id, best_score = archetype.id, score

    return ArchetypeChoice(id=best_id, confidence=round(min(best_score, 0.95), 2))


def feature_criticality(catalog: Catalog, archetype_id: str, feature_id: str) -> Criticality:
    archetype = next(a for a in catalog.archetypes if a.id == archetype_id)
    for f in archetype.features:
        if f.featureId == feature_id:
            return f.criticality
    return "should"
