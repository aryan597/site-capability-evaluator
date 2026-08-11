import json
from pathlib import Path

from app.archetype import choose_archetype, feature_criticality
from app.catalog import Catalog

ROOT = Path(__file__).resolve().parent.parent
CATALOG = Catalog.model_validate(
    json.loads((ROOT / "fixtures" / "catalog.json").read_text(encoding="utf-8"))
)

ACME_PRESENT = ["email-password-login", "has-multistep-forms", "has-simple-forms"]
SHOPWAVE_PRESENT = [
    "public-no-login", "has-search", "has-simple-forms",
    "has-multistep-forms", "has-payment-forms", "uses-iframes",
]


def test_acme_features_pick_saas_app():
    assert choose_archetype(CATALOG, ACME_PRESENT, hint="saas-app").id == "saas-app"


def test_shopwave_features_pick_ecommerce_without_hint():
    choice = choose_archetype(CATALOG, SHOPWAVE_PRESENT, hint=None)
    assert choice.id == "ecommerce"
    assert choice.confidence > 0.7


def test_unknown_hint_is_ignored():
    with_bogus = choose_archetype(CATALOG, SHOPWAVE_PRESENT, hint="blog")
    without = choose_archetype(CATALOG, SHOPWAVE_PRESENT, hint=None)
    assert with_bogus == without


def test_criticality_carried_from_archetype_bundle():
    assert feature_criticality(CATALOG, "saas-app", "has-multistep-forms") == "should"
    assert feature_criticality(CATALOG, "ecommerce", "has-multistep-forms") == "must"


def test_criticality_defaults_to_should_outside_bundle():
    # uses-iframes is not in saas-app's bundle
    assert feature_criticality(CATALOG, "saas-app", "uses-iframes") == "should"
