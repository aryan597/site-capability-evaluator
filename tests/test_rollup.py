"""Unit tests for the deterministic rollup, plus reproduction of both
worked fixtures (the graded contract)."""

import json
from pathlib import Path

import pytest

from app.catalog import Catalog
from app.rollup import rollup

ROOT = Path(__file__).resolve().parent.parent
CATALOG = Catalog.model_validate(
    json.loads((ROOT / "fixtures" / "catalog.json").read_text(encoding="utf-8"))
)


def load_expected(name: str) -> dict:
    path = ROOT / "fixtures" / "sites" / f"{name}.expected.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- the subtle case, isolated -------------------------------------------

def test_level_and_criticality_roll_up_independently():
    """text-input: @2(must) + @2(must) + @3(should) => @3 must.
    Level comes from a 'should' demand; criticality from 'must' demands."""
    out = rollup(["has-search", "has-simple-forms", "has-payment-forms"], CATALOG)
    text_input = next(c for c in out if c.capabilityId == "text-input")
    assert text_input.minLevel == 3
    assert text_input.criticality == "must"
    assert set(text_input.sourceFeatureIds) == {
        "has-search", "has-simple-forms", "has-payment-forms",
    }


def test_single_feature_passthrough():
    out = rollup(["uses-iframes"], CATALOG)
    assert len(out) == 1
    only = out[0]
    assert (only.capabilityId, only.minLevel, only.criticality) == ("iframe-traversal", 2, "must")
    assert only.sourceFeatureIds == ["uses-iframes"]


def test_empty_input_empty_output():
    assert rollup([], CATALOG) == []


def test_duplicate_feature_ids_do_not_double_count():
    once = rollup(["uses-iframes"], CATALOG)
    twice = rollup(["uses-iframes", "uses-iframes"], CATALOG)
    assert once == twice


def test_unknown_feature_id_raises():
    with pytest.raises(ValueError):
        rollup(["not-a-feature"], CATALOG)


# --- the graded contract: both fixtures, exactly --------------------------

@pytest.mark.parametrize("site", ["acme-hr", "shopwave"])
def test_reproduces_expected_fixture(site: str):
    expected = load_expected(site)
    present = [f["featureId"] for f in expected["inferredFeatures"] if f["present"]]

    got = {
        c.capabilityId: (c.minLevel, c.criticality, set(c.sourceFeatureIds))
        for c in rollup(present, CATALOG)
    }
    want = {
        c["capabilityId"]: (c["minLevel"], c["criticality"], set(c["sourceFeatureIds"]))
        for c in expected["requiredCapabilities"]
    }
    assert got == want
