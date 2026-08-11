# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A take-home exercise: build the **Evaluator**, a stateless HTTP service that answers one question — *"Given this company's website, which agent capabilities (at what minimum level) would testing it require?"* The full brief is in [README.md](README.md); read it before making design decisions. As of now the repo contains only the brief and fixtures — **no implementation, build tooling, or tests exist yet**, and it is not a git repository. When code is added, record the actual build/test/run commands here.

## Core architecture (from the brief)

- **Input:** `POST /v1/evaluate`. Two evidence modes: **pass-in** (caller supplies captured pages; no fetching; the core, reproducible deliverable) and **live** (crawl from a domain; mostly a design exercise, thin implementation is bonus-only).
- **Catalog** (`fixtures/catalog.json` models the provided API): versioned, immutable definitions of features → required capabilities, plus archetypes. Fetch at runtime, cache in memory by version, never hard-code contents. The toy has 10 features / 13 capabilities; design for the real ~70 / ~155.
- **Pipeline:** infer which features the site has (LLM/fuzzy) → derive required capabilities from the catalog `requires` map (pure deterministic code) → structured response with confidence + evidence. Keep the deterministic rollup cleanly separated from the LLM part; it's explicitly graded.
- Also required: `GET /health`, `GET /version`, an OpenAPI 3.1 doc that matches the implementation, a Dockerfile that starts from env config alone (`CATALOG_BASE`, `LLM_API_KEY`, provider/model — nothing hard-coded).

## The rollup rule (graded contract — do not break)

`fixtures/sites/*.expected.json` are the graded contract for the deterministic part: the set of present features and the full `requiredCapabilities` rollup (capabilityId, minLevel, criticality, sourceFeatureIds). Confidence values and evidence strings are illustrative only; lists are unordered.

The rule the fixtures pin down: for each capability required by any *present* feature,
- `minLevel` = **max** level across contributing features,
- `criticality` = **strictest** criticality across contributing features (must > should > nice),
- and these roll up **independently** — the subtle case in `shopwave.expected.json` is `text-input`, where level 3 comes from a `should` requirement and `must` comes from different features at level 2, yielding `text-input @3 (must)`. A "take everything from the strictest feature" shortcut fails this.
- `sourceFeatureIds` lists every present feature that requires the capability.
- Feature `criticality` in `inferredFeatures` is carried through from the catalog (the matched archetype's feature list).

Any implementation change must keep both fixtures reproducing exactly, and the pass-in path must be deterministic: same request + catalog version + evaluator version ⇒ same answer (tested in CI without flaking).

## Hard constraints (explicitly reviewed)

- **The boundary:** the Evaluator never reads or reasons about the agent's *current* capability levels and never computes readiness/fit scores. If a change seems to need current levels, it's out of scope by design.
- **Secrets:** `access.credentials` / `sessionCookies` and anything fetched with them live in memory only — never logged, persisted, cached, echoed in `trace` or responses, or leaked via error paths.
- **Stateless:** no database, no persistence; the only allowed state is the in-memory catalog cache keyed by version.
- **Gated sites are not errors:** a login wall you can't pass returns 200 with `accessOutcome: "public-only"` (or `"blocked"`) and reduced confidence. Non-200s are reserved for malformed requests, unreachable catalog, or a nonexistent pinned catalog version.
- **No LLM arithmetic:** anything that must be exact (the rollup, criticality/level math) runs in plain code, not in a prompt.

## Out of scope — do not build

Readiness/fit scoring, real login/MFA automation against third-party sites, any UI, database, persistence, CRM integrations, or catalog authoring/editing.

## Judgment over feature count

The submission is graded on the design decisions in README §5 (fuzzy/deterministic boundary, LLM-at-scale strategy, determinism/testability, confidence semantics, live-investigation design, API contract) more than on surface area. Decisions the human author must own belong in the project README, not just in code.
