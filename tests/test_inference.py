import asyncio
import json
from pathlib import Path

import pytest

from app.catalog import Catalog
from app.inference import BAND_SCORES, PageEvidence, infer_features
from app.llm import LLMError
from tests.fakes import ScriptedLLM, verdict_json

ROOT = Path(__file__).resolve().parent.parent
CATALOG = Catalog.model_validate(
    json.loads((ROOT / "fixtures" / "catalog.json").read_text(encoding="utf-8"))
)

PAGES = [PageEvidence(url="https://x.example", sourceType="marketing", text="hello")]


def test_one_call_per_cluster_and_every_feature_gets_a_verdict():
    llm = ScriptedLLM({
        "Access & Auth": verdict_json(),
        "App Architecture": verdict_json(),
        "Forms & Input": verdict_json(),
    })
    out = asyncio.run(infer_features(llm, CATALOG, PAGES))
    assert sorted(llm.calls) == ["Access & Auth", "App Architecture", "Forms & Input"]
    assert {f.featureId for f in out} == {f.id for f in CATALOG.features}


def test_bands_map_to_numbers_and_unknown_ids_are_dropped():
    llm = ScriptedLLM({
        "Access & Auth": verdict_json(
            {"featureId": "email-password-login", "present": True,
             "confidence": "certain", "evidence": "login page shows Email + Password."},
            {"featureId": "hallucinated-feature", "present": True,
             "confidence": "certain", "evidence": "made up"},
        ),
        "App Architecture": verdict_json(),
        "Forms & Input": verdict_json(),
    })
    out = asyncio.run(infer_features(llm, CATALOG, PAGES))
    by_id = {f.featureId: f for f in out}
    assert "hallucinated-feature" not in by_id
    login = by_id["email-password-login"]
    assert login.present is True
    assert login.confidence == BAND_SCORES["certain"]


def test_missing_verdicts_default_to_absent_unsure():
    llm = ScriptedLLM({
        "Access & Auth": verdict_json(),
        "App Architecture": verdict_json(),
        "Forms & Input": verdict_json(),
    })
    out = asyncio.run(infer_features(llm, CATALOG, PAGES))
    assert all(not f.present and f.confidence == BAND_SCORES["unsure"] for f in out)


def test_unknown_confidence_word_falls_back_to_unsure():
    llm = ScriptedLLM({
        "Access & Auth": verdict_json(
            {"featureId": "sso-login", "present": True,
             "confidence": "SUPER-SURE", "evidence": "Sign in with Google button."},
        ),
        "App Architecture": verdict_json(),
        "Forms & Input": verdict_json(),
    })
    out = asyncio.run(infer_features(llm, CATALOG, PAGES))
    sso = next(f for f in out if f.featureId == "sso-login")
    assert sso.confidence == BAND_SCORES["unsure"]


def test_non_json_reply_raises_llm_error():
    llm = ScriptedLLM({
        "Access & Auth": "I think the site probably has a login page.",
        "App Architecture": verdict_json(),
        "Forms & Input": verdict_json(),
    })
    with pytest.raises(LLMError):
        asyncio.run(infer_features(llm, CATALOG, PAGES))
