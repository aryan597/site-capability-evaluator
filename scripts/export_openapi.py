"""Export the app's OpenAPI document to openapi.yaml.

The committed openapi.yaml is the published contract; it is generated
from the implementation and a test asserts they never drift apart.
Run after any change to routes or models:

    python scripts/export_openapi.py
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import create_app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "openapi.yaml"


def main() -> None:
    schema = create_app().openapi()
    OUT.write_text(yaml.safe_dump(schema, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {OUT} (openapi {schema['openapi']})")


if __name__ == "__main__":
    main()
