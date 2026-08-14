"""Deterministic capability rollup: the exact, graded core.

Pure function of (present feature ids, catalog). No LLM, no I/O.

The rule (pinned by fixtures/sites/*.expected.json):
for each capability required by any PRESENT feature,
  - minLevel    = max of the contributing features' minLevel demands
  - criticality = strictest of the contributing criticalities (must > should > nice)
  - the two roll up INDEPENDENTLY; level and criticality may come from
    different features (shopwave's text-input: @3 from a "should" demand,
    "must" from level-2 demands => text-input @3 must)
  - sourceFeatureIds = every present feature that requires the capability
"""

from pydantic import BaseModel

from app.catalog import Catalog, Criticality, strictest


class RolledCapability(BaseModel):
    capabilityId: str
    minLevel: int
    criticality: Criticality
    sourceFeatureIds: list[str]
    reasoning: str


def rollup(present_feature_ids: list[str], catalog: Catalog) -> list[RolledCapability]:
    features = catalog.features_by_id()
    unknown = [fid for fid in present_feature_ids if fid not in features]
    if unknown:
        raise ValueError(f"unknown feature ids: {unknown}")

    demands: dict[str, list[tuple[str, int, Criticality]]] = {}
    for fid in sorted(set(present_feature_ids)):
        for req in features[fid].requires:
            demands.setdefault(req.capabilityId, []).append((fid, req.minLevel, req.criticality))

    rolled: list[RolledCapability] = []
    for cap_id in sorted(demands):
        entries = demands[cap_id]
        level = max(lvl for _, lvl, _ in entries)
        crit: Criticality = "nice"
        for _, _, c in entries:
            crit = strictest(crit, c)
        cited = "; ".join(f"{fid} requires @{lvl} ({c})" for fid, lvl, c in entries)
        rolled.append(
            RolledCapability(
                capabilityId=cap_id,
                minLevel=level,
                criticality=crit,
                sourceFeatureIds=[fid for fid, _, _ in entries],
                reasoning=f"{cited}. minLevel = max = {level}; criticality = strictest = {crit}.",
            )
        )
    return rolled
