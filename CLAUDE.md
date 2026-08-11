# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A take-home submission: the **Evaluator**, a stateless FastAPI service answering *"which agent capabilities (at what minimum level) would testing this site require?"* The assignment brief is [docs/BRIEF.md](docs/BRIEF.md); the solution write-up (design decisions, §5 answers) is [README.md](README.md). Python 3.10+, no database, no persistence.

## Commands

```bash
python -m pytest tests/ -q                      # full suite; no network, no API key needed
python -m pytest tests/test_rollup.py -q        # single file; -k <name> for a single test
python scripts/export_openapi.py                # regenerate openapi.yaml after route/model changes
uvicorn mock_catalog.server:app --port 9001     # mock catalog API (serves fixtures/catalog.json)
uvicorn app.main:app --port 8000                # the evaluator (needs CATALOG_BASE + LLM key env)
```

A real evaluation needs env: `CATALOG_BASE`, `ANTHROPIC_API_KEY` (or `LLM_API_KEY`). Tests never do.

## Architecture

Pipeline in [app/evaluator.py](app/evaluator.py) — the LLM appears exactly once:

```
pages → [LLM] infer features (app/inference.py, one call per cluster, parallel)
      → choose archetype (app/archetype.py, deterministic F1 score)
      → capability rollup (app/rollup.py, deterministic — THE GRADED PART)
      → confidence math (app/evaluator.py, fixed formulas)
```

- **LLM seam**: [app/llm.py](app/llm.py) — one-method protocol; Anthropic impl + `tests/fakes.py` ScriptedLLM. The LLM only ever judges feature presence and picks a confidence *word* (mapped to numbers in code: certain .95 / high .85 / likely .7 / unsure .5 / weak .3). Never let the LLM do arithmetic or touch capabilities.
- **Catalog client**: [app/catalog.py](app/catalog.py) — HTTP fetch, cache keyed by version (immutable ⇒ cached forever), latest re-fetched with stale fallback when the API is down. Accepts an injected httpx transport for tests.
- **HTTP surface**: [app/main.py](app/main.py) — `create_app()` factory with injectable settings/catalog/llm. Error taxonomy in its docstring; bodies always `{"error": {code, message}}`.

## Invariants (graded — do not break)

- **Rollup rule**: minLevel = max across contributing features; criticality = strictest; rolled up **independently** (shopwave's `text-input @3 must` mixes sources). `tests/test_rollup.py` pins both fixtures exactly — they must always pass.
- **Determinism**: with the LLM faked, responses are **byte-identical** (`tests/test_determinism.py`). Don't introduce unordered iteration, timestamps, or raw floats into responses; confidences are rounded to 2 decimals; features emit in catalog order, capabilities sorted by id.
- **Secrets**: `access.credentials`/`sessionCookies` are never logged, cached, echoed in responses/trace/errors. The 422 handler reports field locations only, never values. `tests/test_api.py` greps responses for planted secrets.
- **The boundary**: never read/compute the agent's current capability levels or any readiness/fit score.
- **Gated site is a 200** with `accessOutcome: "public-only"`, not an error.
- **openapi.yaml is generated** — edit routes/models, then run the export script; `tests/test_openapi.py` fails on drift. Never hand-edit openapi.yaml.
