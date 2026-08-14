# Site Capability Evaluator

A stateless HTTP service that answers one question: **given a company's website, which capabilities would our browser agent need — at what minimum level — to test it?** It infers site *features* from page evidence (LLM), then derives *required capabilities* deterministically from the versioned catalog. It never scores readiness or reads the agent's current levels — that happens downstream, outside this service.

The original assignment brief lives in [docs/BRIEF.md](docs/BRIEF.md).

## How to run

Two processes: the mock Catalog API (stands in for the real one) and the evaluator.

```bash
pip install -r requirements.txt

# terminal 1 — mock catalog API
uvicorn mock_catalog.server:app --port 9001

# terminal 2 — the evaluator
export CATALOG_BASE=http://127.0.0.1:9001
export ANTHROPIC_API_KEY=sk-ant-...        # or LLM_API_KEY
uvicorn app.main:app --port 8000
```

Evaluate a fixture:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d @fixtures/sites/acme-hr.input.json
```

### Running against a local model (no API key)

Anything that speaks the Anthropic Messages API works. With LM Studio serving a model locally:

```bash
export CATALOG_BASE=http://127.0.0.1:9001
export LLM_BASE_URL=http://127.0.0.1:1234
export LLM_MODEL=hermes-3-llama-3.1-8b     # whatever model LM Studio has loaded
uvicorn app.main:app --port 8000
```

Same code path as production — only env differs. (Small local models produce noticeably weaker feature verdicts than Claude; see the accuracy discussion in §2 below.)

### Docker

```bash
docker build -t evaluator .
docker run -p 8000:8000 -e CATALOG_BASE=... -e LLM_API_KEY=... evaluator
```

The container starts from env alone. Configuration:

| Env var | Default | Meaning |
|---|---|---|
| `CATALOG_BASE` | `http://127.0.0.1:9001` | Base URL of the Catalog API |
| `LLM_PROVIDER` | `anthropic` | Provider behind the one-method LLM seam |
| `LLM_MODEL` | `claude-sonnet-5` | Model id |
| `LLM_API_KEY` / `ANTHROPIC_API_KEY` | — | Key (required only for real evaluations) |
| `LLM_BASE_URL` | — | Point the Anthropic-compatible client at another server (e.g. LM Studio); key becomes optional |
| `CATALOG_TIMEOUT_S` | `5` | Catalog fetch timeout |
| `LLM_MAX_CONCURRENCY` | `4` | Parallel cluster calls cap |

### Tests

```bash
python -m pytest tests/ -q
```

No API key and no network needed: the LLM is replaced by a scripted fake, the catalog API by an in-process transport. Covered: rollup unit tests, exact reproduction of **both worked fixtures** (including the subtle case), byte-identical determinism, secrets non-leakage, the error taxonomy, and an OpenAPI-sync guard.

`openapi.yaml` is generated from the implementation (`python scripts/export_openapi.py`); a test fails if the committed file drifts from the app.

---

## The decisions (brief §5)

### 1. The fuzzy / deterministic boundary

The LLM answers exactly one kind of question — a judgment call: *"given these captured pages, is this feature present, and how sure are you?"* Everything else is plain code:

- capability rollup (the graded contract) — pure function in [app/rollup.py](app/rollup.py)
- archetype choice — a measurement (F1 of bundle coverage vs. feature explanation) in [app/archetype.py](app/archetype.py)
- all confidence arithmetic — fixed formulas in [app/evaluator.py](app/evaluator.py)

The rule I inferred from the fixtures, and the reason the shopwave case is subtle: when several present features demand the same capability, **minLevel and criticality roll up independently** — level is the *max* across demands (the agent must satisfy the hardest one), criticality is the *strictest* across demands (the requirement is as non-negotiable as its most insistent source). They can come from different features: shopwave's `text-input` gets level 3 from a `should` demand and `must` from two level-2 demands ⇒ `@3 must`. Copying both values from the single strictest feature is the bug the fixture catches.

The LLM also never emits numbers: it picks a confidence *word* from a fixed list, and code maps words to numbers. If you ever feel the LLM should do arithmetic here, something has leaked across the boundary.

### 2. LLM strategy at production scale

One call per **feature cluster**, run in parallel (bounded by `LLM_MAX_CONCURRENCY`). Each prompt carries only that cluster's feature questions plus the page evidence.

Why this beats the alternatives at ~70 features / ~155 capabilities:

- **One mega-prompt** is cheapest but degrades: long feature lists dilute attention, and prompt size grows with the catalog — a known accuracy cliff you can't tune away.
- **One call per feature** is the accuracy ceiling but ~70 sequential-ish calls of mostly-identical evidence: cost and latency scale linearly with the catalog.
- **Per cluster** bounds prompt size regardless of catalog growth (clusters are the catalog's own grouping), keeps latency ≈ one call (parallel), and cost at ~8–12 calls. Note the capability count (155) never enters a prompt at all — capabilities are handled deterministically.

The evidence side of the prompt is the real scale risk: page text is capped per page today; at production I'd add an extraction/summarization pass so evidence stays bounded too.

### 3. Determinism & testability

Claim: **the service adds zero nondeterminism of its own.** The only nondeterministic component is the LLM, and it is confined behind a one-method seam ([app/llm.py](app/llm.py)).

- In CI, the seam is filled by a scripted fake, and [tests/test_determinism.py](tests/test_determinism.py) asserts **byte-identical** responses across repeated calls and fresh app instances. No tolerances, no flakes. This proves ordering, dict-iteration, float and concurrency behavior in *our* code are all stable (cluster results are gathered concurrently but reassembled in sorted order).
- Against the real LLM, determinism is best-effort by construction: a pinned model id and word-band confidences (a small logit wobble rarely flips a *band*, where it would always flip a raw float). Current Claude models accept no sampling parameters at all — sending `temperature` is an API error — so there is no knob beyond the model pin; for local Anthropic-compatible servers, which do honor sampling, temperature is pinned to 0. Stated tolerance: feature *verdicts* are stable in practice; if a run flips a genuinely borderline verdict, the response changes — that residual is inherent to any LLM-backed service and is why the deterministic core is tested separately from it.

The determinism key is `(request, catalogVersion, evaluatorVersion)` — both versions are echoed in every response.

### 4. Confidence

Confidence means *"how sure are we that what we observed is true"* — never agent readiness or fit (that's the §2 boundary).

| Number | Rule | Rationale |
|---|---|---|
| per feature | LLM picks a word → certain 0.95 / high 0.85 / likely 0.7 / unsure 0.5 / weak 0.3 | honest about real granularity; stable across runs; every number has a written meaning |
| per capability | **max** over the present features that demand it | a capability is required if *any* source feature is real — we're as sure as our best reason. (Noisy-OR would overclaim: features seen on the same pages aren't independent evidence.) |
| overall | criticality-weighted mean (must×3 / should×2 / nice×1) × access factor: authenticated 1.0 / partial 0.9 / public-only 0.85 / blocked 0.6 | a shaky must matters more than a shaky nice; and if we never saw the real product we can't verify things correctly, so the whole report's trust number must visibly drop |

Open question I'd revisit with real data: whether the access factors are well-calibrated. The *structure* (weaker evidence ⇒ visibly lower number) I'm confident in; the exact constants are a first guess and are documented so they can be tuned.

### 5. Live investigation (designed, not built)

v1 is pass-in only; a request without `content.pages` returns `501 LIVE_MODE_NOT_IMPLEMENTED`. The design I'd build:

**Adaptive, researcher-style crawl with hard budgets.** Fetch the homepage, extract text and links; then loop: *"given the feature questions still unanswered and these candidate links, which page is most worth fetching next?"* — a tiny navigation decision made by a cheap fast model (Haiku-class), not the main model. Repeat until the page budget (`maxPages`), time budget (`timeBudgetMs`), or an answered-enough threshold is hit. The expensive model only runs the normal cluster inference at the end, over whatever evidence was gathered.

- **Gated sites:** not a failure — a pivot. The login wall itself is evidence (login/SSO features); then the crawler shifts to public surfaces: pricing, docs, signup structure, status pages, third-party listings. The response reports `accessOutcome: "public-only"` and the access factor lowers overall confidence — already implemented on the pass-in path.
- **Cost control:** the navigation calls are small and cheap; the page budget caps everything. Under a tight budget it degrades gracefully toward a playbook (/, /pricing, /login, /signup, docs) — the fixed list is the floor, not the strategy.
- **Safety/politeness:** obey robots.txt, per-domain rate limit and concurrency of 1, identifying user-agent, GET only, no form submissions, and **never** attempt real logins with supplied credentials against third-party IdPs (design boundary; credentials handling stays in-memory as on the pass-in path).

### 6. The contract

`openapi.yaml` (OpenAPI 3.1) is generated from the FastAPI models and route metadata, and a test pins the committed file to the implementation — "stays in sync" is enforced, not promised. Error taxonomy (body is always `{"error": {"code", "message"}}`):

| Status | Code | When |
|---|---|---|
| 422 | `VALIDATION_ERROR` | body doesn't match the schema (reports field *locations only* — values are never echoed, so secrets can't leak via errors) |
| 400 | `CATALOG_VERSION_NOT_FOUND` | pinned version doesn't exist |
| 501 | `LIVE_MODE_NOT_IMPLEMENTED` | no `content.pages` in v1 |
| 502 | `LLM_ERROR` | provider failure / unusable output |
| 503 | `CATALOG_UNAVAILABLE` | catalog API down and nothing cached |

A gated site is **not** an error: 200 with `accessOutcome: "public-only"` and lower confidence. `trace` is off by default and appears only with `options.debug: true`; it contains derived values only (cluster count, present feature ids, access factor) — never request contents, never credentials.

Secrets: `access.credentials` / `sessionCookies` parse into memory, are never logged (there is no request-body logging), never cached, never echoed in responses, `trace`, or error paths, and go out of scope at end of request — the service has no persistence at all.

---

## The prompts

One system prompt + one user prompt per cluster — both in [app/inference.py](app/inference.py). The system prompt fixes the rules (judge only from provided pages; absence of evidence = absent; evidence must cite a page; confidence is one of five words; JSON only). The user prompt is assembled per cluster: the cluster's feature ids + questions, then the captured pages (url, sourceType, title, capped text).

## Where the toy let me cut corners

- **Evidence size:** page text capped at 4k chars/page works for fixtures; production needs an extraction pass and a token budget per cluster call.
- **Catalog cache:** unbounded in-memory dict — fine for one active version + a few pins; production wants an LRU bound and a metric on fallback-serves.
- **Archetype constants** (F1, hint bonus 0.1) and **confidence constants** are first guesses; with labeled data I'd calibrate them.
- **`partial`/`mixed`/live outcomes** are modeled in the schema but only reachable once live mode exists.

## With two more weeks

Retry/backoff + token/cost accounting on LLM calls; structured logging with a redaction layer as defense-in-depth (today safety comes from not logging bodies at all); an eval set of labeled sites to measure feature-inference accuracy per cluster and calibrate confidence; the live-mode crawler above; concurrency limits and load-shedding; contract tests run against the container in CI.

**The 8th hour** would go to the eval set — accuracy of feature inference is the one number this service's usefulness actually hangs on, and nothing here measures it yet.
