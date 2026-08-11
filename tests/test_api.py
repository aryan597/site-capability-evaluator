"""End-to-end API tests: full pipeline with a scripted LLM and a fake
catalog API — real HTTP semantics, no network, fully deterministic."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import ScriptedLLM, fixture_catalog_client, verdict, verdict_json

ROOT = Path(__file__).resolve().parent.parent

SETTINGS = Settings(
    catalog_base="http://catalog.test", llm_provider="fake", llm_model="fake",
    llm_api_key=None, catalog_timeout_s=5, llm_max_concurrency=4,
)

# Scripted verdicts matching what a competent LLM says about acme-hr.
ACME_REPLIES = {
    "Access & Auth": verdict_json(
        verdict("email-password-login", True, "certain",
                "login page: 'Email address' + 'Password' fields."),
        verdict("public-no-login", False, "high", "product is behind a login wall."),
        verdict("sso-login", False, "high", "no SSO providers mentioned."),
        verdict("behind-bot-protection", False, "high", "no WAF/bot interstitial evidence."),
    ),
    "App Architecture": verdict_json(
        verdict("is-spa", False, "unsure", "no evidence either way in text."),
        verdict("uses-iframes", False, "unsure", "no embedded content mentioned."),
    ),
    "Forms & Input": verdict_json(
        verdict("has-simple-forms", True, "high", "login + signup have text/email inputs."),
        verdict("has-multistep-forms", True, "certain", "signup: 'Step 1 of 3'."),
        verdict("has-payment-forms", False, "high", "no card fields on captured pages."),
        verdict("has-search", False, "high", "no search box mentioned."),
    ),
}


def make_client(replies=None) -> TestClient:
    app = create_app(
        settings=SETTINGS,
        catalog_client=fixture_catalog_client(),
        llm=ScriptedLLM(replies or ACME_REPLIES),
    )
    return TestClient(app)


def load_fixture(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / "sites" / name).read_text(encoding="utf-8"))


def test_acme_hr_end_to_end_matches_expected_contract():
    response = make_client().post("/v1/evaluate", json=load_fixture("acme-hr.input.json"))
    assert response.status_code == 200
    body = response.json()
    expected = load_fixture("acme-hr.expected.json")

    assert body["catalogVersion"] == expected["catalogVersion"]
    assert body["archetype"]["id"] == "saas-app"

    got_caps = {
        c["capabilityId"]: (c["minLevel"], c["criticality"], set(c["sourceFeatureIds"]))
        for c in body["requiredCapabilities"]
    }
    want_caps = {
        c["capabilityId"]: (c["minLevel"], c["criticality"], set(c["sourceFeatureIds"]))
        for c in expected["requiredCapabilities"]
    }
    assert got_caps == want_caps

    present = {f["featureId"] for f in body["inferredFeatures"] if f["present"]}
    assert present == {f["featureId"] for f in expected["inferredFeatures"] if f["present"]}

    inv = body["investigation"]
    assert inv["mode"] == "passed-in"
    assert inv["accessOutcome"] == "public-only"  # gated site, still a 200
    assert inv["pagesUsed"] == 3
    assert 0 < body["overallConfidence"] < 1
    assert "trace" not in body  # debug off => no trace key at all


def test_secrets_never_appear_in_response_even_with_debug():
    request = load_fixture("acme-hr.input.json")
    request["access"] = {
        "loginUrl": "https://acme-hr.example/login",
        "credentials": {"username": "eval@corp.example", "password": "hunter2-s3cret"},
        "sessionCookies": [{"name": "sid", "value": "topsecret-cookie", "domain": "acme-hr.example"}],
    }
    request["options"] = {"debug": True}

    response = make_client().post("/v1/evaluate", json=request)
    assert response.status_code == 200
    raw = response.text
    for secret in ("hunter2-s3cret", "topsecret-cookie", "eval@corp.example"):
        assert secret not in raw
    assert response.json()["trace"] is not None  # debug on => trace exists, minus secrets


def test_unknown_pinned_catalog_version_is_400():
    request = load_fixture("acme-hr.input.json")
    request["catalogVersion"] = "1999-01-01T00:00:00Z"
    response = make_client().post("/v1/evaluate", json=request)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CATALOG_VERSION_NOT_FOUND"


def test_missing_content_is_501_live_mode():
    response = make_client().post("/v1/evaluate", json={"site": {"domain": "x.example"}})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "LIVE_MODE_NOT_IMPLEMENTED"


def test_malformed_body_is_422_and_does_not_echo_values():
    response = make_client().post(
        "/v1/evaluate",
        json={"site": {"domain": ""}, "content": {"pages": [{"url": "u", "sourceType": "blog"}]},
              "access": {"credentials": {"password": "oops-a-secret"}}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "oops-a-secret" not in response.text
