"""Determinism of the pass-in path.

Claim under test: the service adds ZERO nondeterminism of its own. With
the LLM pinned (scripted fake), the same request + catalog version +
evaluator version yields a byte-identical response — across repeated
calls AND across fresh app instances (fresh event loops, fresh caches).

The real LLM is the only nondeterministic component; it is confined
behind the provider seam and mitigated there (temperature 0, word-band
confidences). That split is what makes this test meaningful rather than
a flake-magnet.
"""

import json
from pathlib import Path

from tests.test_api import load_fixture, make_client


def test_repeated_calls_are_byte_identical():
    client = make_client()
    request = load_fixture("acme-hr.input.json")
    bodies = {client.post("/v1/evaluate", json=request).text for _ in range(5)}
    assert len(bodies) == 1


def test_fresh_app_instances_agree():
    request = load_fixture("acme-hr.input.json")
    first = make_client().post("/v1/evaluate", json=request).text
    second = make_client().post("/v1/evaluate", json=request).text
    assert first == second
