"""The committed openapi.yaml must match the implementation exactly.

If this fails, run:  python scripts/export_openapi.py
"""

from pathlib import Path

import yaml

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent


def test_committed_openapi_matches_app():
    committed = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    assert committed == create_app().openapi()


def test_openapi_is_3_1_and_documents_the_surface():
    schema = create_app().openapi()
    assert schema["openapi"].startswith("3.1")
    assert set(schema["paths"]) == {"/health", "/version", "/v1/evaluate"}
    evaluate = schema["paths"]["/v1/evaluate"]["post"]
    assert {"200", "400", "422", "501", "502", "503"} <= set(evaluate["responses"])
