# Site Capability Evaluator

A stateless HTTP service that answers one question: given a company's website, which capabilities would our browser agent need, at what minimum level, to test it?

It infers site *features* from page evidence using an LLM, then derives *required capabilities* from the versioned catalog using plain code. It never reads the agent's current levels and never computes a readiness or fit score; that happens downstream.

## How to run

Copy the example config and fill in your key:

```bash
cp .env.example .env
```

Then edit `.env` and set `ANTHROPIC_API_KEY`. The file is gitignored. Real environment variables always take precedence over `.env`, so the container path is unaffected.

Install and start the two processes:

```bash
pip install -r requirements.txt
```

```bash
uvicorn mock_catalog.server:app --port 9001
```

```bash
uvicorn app.main:app --port 8000
```

Evaluate a fixture:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/evaluate -H "Content-Type: application/json" -d @fixtures/sites/acme-hr.input.json
```

### Running against a local model, no API key

Anything that speaks the Anthropic Messages API works. With LM Studio serving a model locally, set these in `.env` (or as env vars) and restart:

```
LLM_BASE_URL=http://127.0.0.1:1234
LLM_MODEL=hermes-3-llama-3.1-8b
```

Same code path, only configuration differs. This was used to produce the model comparison in section 3.

### Docker

```bash
docker build -t evaluator .
```

```bash
docker run -p 8000:8000 -e CATALOG_BASE=... -e LLM_API_KEY=... evaluator
```

The container starts from environment alone. Full configuration surface:

| Env var | Default | Meaning |
|---|---|---|
| `CATALOG_BASE` | `http://127.0.0.1:9001` | Base URL of the Catalog API |
| `LLM_PROVIDER` | `anthropic` | Provider behind the one-method LLM seam |
| `LLM_MODEL` | `claude-sonnet-5` | Model id |
| `LLM_API_KEY` or `ANTHROPIC_API_KEY` | none | Key, required only for real evaluations |
| `LLM_BASE_URL` | none | Point the client at another Anthropic-compatible server. Key becomes optional. |
| `CATALOG_TIMEOUT_S` | `5` | Catalog fetch timeout |
| `LLM_MAX_CONCURRENCY` | `4` | Cap on parallel cluster calls |

### Tests

```bash
python -m pytest tests/ -q
```

No API key and no network needed. The LLM is replaced by a scripted fake and the catalog API by an in-process transport. Coverage: rollup unit tests, exact reproduction of both worked fixtures including the subtle case, byte-identical determinism, secrets non-leakage, the error taxonomy, and an OpenAPI sync guard.

`openapi.yaml` is generated from the implementation by `python scripts/export_openapi.py`, and a test fails if the committed file drifts from the app.

---

## The decisions (brief section 5)

### 1. The fuzzy and deterministic boundary

The LLM answers exactly one kind of question, and it is a genuine judgment call: given these captured pages, is this feature present, and how sure are you? Everything else is plain code:

- capability rollup, the graded contract, a pure function in [app/rollup.py](app/rollup.py)
- archetype choice, a measurement rather than an opinion, in [app/archetype.py](app/archetype.py)
- all confidence arithmetic, fixed formulas, in [app/evaluator.py](app/evaluator.py)

The rule I inferred from the fixtures: when several present features demand the same capability, **minLevel and criticality roll up independently**. Level is the max across demands, because the agent must satisfy the hardest one. Criticality is the strictest across demands, because the requirement is as non-negotiable as its most insistent source. The two can come from different features. Shopwave's `text-input` takes level 3 from a `should` demand and `must` from two level-2 demands, giving `text-input @3 (must)`. Copying both values from whichever single feature looks strictest is the bug that fixture is built to catch.

The LLM also never emits a number. It picks a confidence word from a fixed list and code maps words to values. Two reasons. Self-reported probabilities from a model are poorly calibrated, and the apparent precision is fake anyway: asked for a float, models cluster on a handful of round values. Naming five bands makes the real granularity explicit and gives every value a written meaning. The principled alternative would be reading token logprobs for a true probability, which the API does not expose; the practical upgrade is calibrating the band values against measured outcomes, which needs the eval set described at the end.

### 2. LLM strategy at production scale

One call per feature cluster, run in parallel, bounded by `LLM_MAX_CONCURRENCY`. Each prompt carries only that cluster's feature questions plus the page evidence.

Why this beats the alternatives at roughly 70 features and 155 capabilities:

- **One call per feature** is the accuracy ceiling but sends nearly identical evidence 70 times. Cost and latency scale linearly with catalog size, forever.
- **One mega-prompt** is one call, but asks 70 questions in one context. Attention degrades across long lists and the prompt grows every time someone adds a feature. That is a cliff you cannot tune away.
- **Per cluster** bounds prompt size regardless of catalog growth, because clusters are the catalog's own grouping. Latency stays close to a single call because the calls are parallel, and cost lands around 8 to 12 calls.

The point I would defend hardest in a design review: **the 155 capabilities never enter a prompt at all**. They are resolved from the catalog's requires-map in code, so the expensive half of catalog growth is free.

**What I would do next, and why it is not "fewer calls".** At production scale the cost is dominated by evidence, not questions. Ten pages of roughly 1000 tokens each sent to ten cluster calls is 100k tokens of evidence against about 1k tokens of questions, a ratio of 100 to 1. So the real levers are:

- **Prompt caching.** Put evidence first as a stable prefix, fire one call, wait for its first token, then fire the rest so they read the cached evidence. One extra round trip buys roughly a 90 percent cut on the dominant cost term with no accuracy change.
- **Evidence-first inversion.** One extraction call turns pages into structured observations, then small cheap calls match observations to features. Evidence is sent once. The honest risk is that extraction becomes a lossy compression step, and anything it drops is unrecoverable downstream, so I would want the eval set before shipping it.
- **Two-tier routing.** Run every cluster on a cheap fast model and escalate only the clusters that came back unsure. On most sites most clusters are obviously absent.
- **Result caching** keyed on evidence hash plus catalog version plus evaluator version, which makes re-scoring an unchanged site free.

### 3. Determinism and testability

No LLM is deterministic, from any provider, even at temperature zero: server-side batching changes floating point results, hardware varies between requests, and models are updated under stable names. So the goal is not a deterministic LLM. The goal is:

> Make everything except the LLM deterministic, and make the LLM's output coarse enough that small wobbles do not propagate.

Three mechanisms, none of them tied to a specific provider:

1. **The seam.** One interface with one method in [app/llm.py](app/llm.py). Tests fill it with a scripted fake, so [tests/test_determinism.py](tests/test_determinism.py) can assert **byte-identical** responses across repeated calls and across fresh app instances. No tolerances, no approximate matching, no flakes. That proves ordering, dict iteration, float handling, and concurrency in my code are all stable; cluster results are gathered concurrently but reassembled in sorted order.
2. **Quantization.** The five confidence words act as a rounding step. A borderline verdict flips a float on every run but only flips a word when judgment actually moves a level.
3. **Version pinning.** The determinism key is (request, catalogVersion, evaluatorVersion), and both versions are echoed in every response.

A fourth technique I did not implement but would add: record and replay of real model responses keyed by prompt hash, giving reproducibility against a real model's behavior without network calls.

**Stated tolerance, measured rather than assumed.** Borderline verdicts do flip between runs. Running the acme-hr fixture repeatedly against Claude, a signup step labelled "Billing" was read as a payment form on one run and not the next, on identical input and model, and a flipped verdict changes the derived capability set. That residual is inherent to anything LLM-backed. It is why the deterministic core is tested separately, and why measuring verdict stability is my first next step.

**Model comparison.** Because the seam is provider-agnostic, I ran the same service against Claude and against Hermes 3 Llama 8B hosted locally in LM Studio, changing only environment variables:

| | acme-hr | shopwave | TaskFlow (unseen site) |
|---|---|---|---|
| Claude | 10/10 verdicts, 5/5 capabilities exact | 10/10 verdicts, 7/7 capabilities exact | correctly reads SSO-only, no password field |
| Hermes 3 8B | 9/10, invents a search feature | 9/10, invents a login feature | reads "Continue with Google" as password login |
| Rollup arithmetic | exact | exact | exact |

Verdict quality degrades with model quality. The rollup was arithmetically correct on every run of both models, including the runs where the judgment was wrong. That is the boundary paying for itself: the lever for improving this system is model choice, not engine rewrites.

### 4. Confidence

Confidence expresses how sure we are that what we observed is true.

| Number | Rule | Rationale |
|---|---|---|
| per feature | the model's word mapped to a value: certain 0.95, high 0.85, likely 0.7, unsure 0.5, weak 0.3 | honest about real granularity, stable across runs, every value has a written meaning |
| per capability | max over the present features that demand it | the capability is required if any source feature is real, so we are as sure as our best reason. Noisy-OR would overclaim, since observations from the same pages are not independent evidence. Min would be wrong, since one certain feature alone suffices. |
| overall | criticality-weighted mean (must 3, should 2, nice 1) times an access factor: authenticated 1.0, partial 0.9, public-only 0.85, blocked 0.6 | a shaky must matters more than a shaky nice, and evidence gathered without ever reaching the product cannot be verified, so the report's trust number drops visibly |

Worked example, taken from a real shopwave response. Seven capabilities with confidences 0.95, 0.95, 0.85, 0.95, 0.85, 0.95, 0.85 and weights 2, 2, 3, 3, 3, 3, 3 give a weighted mean of 0.903. Multiplied by the public-only factor of 0.85 that is 0.767, and the response returned 0.77. The number can be recomputed by hand from the response itself, which is what makes it mean something.

The structure I will defend. The exact constants are first guesses and are documented as such so they can be calibrated against data.

### 5. Live investigation (designed, not built)

v1 is pass-in only. A request without `content.pages` returns `501 LIVE_MODE_NOT_IMPLEMENTED` rather than a half-working crawl.

**Adaptive, researcher-style crawl with hard budgets.** Fetch the homepage, extract text and links, then loop: given the feature questions still unanswered and these candidate links, which page is most worth fetching next? That navigation decision is a small prompt on a cheap fast model, not the main one. Repeat until the page budget (`maxPages`), the time budget (`timeBudgetMs`), or an answered-enough threshold is reached. The expensive model runs the normal cluster inference once at the end, over whatever evidence was gathered.

- **Gated sites are a pivot, not a failure.** The login wall is itself evidence, since it reveals password or SSO auth. The crawler then shifts to public surfaces: pricing, docs, signup structure, status pages, third-party listings. The response reports `accessOutcome: "public-only"` and the access factor lowers overall confidence. That part is implemented today on the pass-in path.
- **Cost control.** Navigation calls are small and cheap and the page budget caps everything. Under a tight budget it degrades toward a fixed playbook of `/`, `/pricing`, `/login`, `/signup`, docs. The fixed list is the floor, not the strategy.
- **Safety and politeness.** Obey robots.txt, per-domain rate limiting with concurrency of 1, an identifying user agent, GET only, no form submissions, and never attempt real logins with supplied credentials against third-party identity providers.

Implementation cost is modest because live mode is only an evidence-gathering front end: the pipeline already accepts a list of pages, so everything downstream is built and tested.

### 6. The contract

`openapi.yaml` is OpenAPI 3.1, generated from the FastAPI models and route metadata, and a test pins the committed file to the implementation. Staying in sync is enforced rather than promised.

Error taxonomy. Every error body is `{"error": {"code", "message"}}`.

| Status | Code | When |
|---|---|---|
| 422 | `VALIDATION_ERROR` | body does not match the schema. Reports field locations only, never values, so secrets cannot leak through errors. |
| 400 | `CATALOG_VERSION_NOT_FOUND` | a pinned catalog version does not exist |
| 501 | `LIVE_MODE_NOT_IMPLEMENTED` | no `content.pages` supplied in v1 |
| 502 | `LLM_ERROR` | provider failure or unusable output |
| 503 | `CATALOG_UNAVAILABLE` | catalog API is down and nothing is cached |

A gated site is not an error. It returns 200 with `accessOutcome: "public-only"` and lower confidence.

`trace` is off by default and appears only with `options.debug: true`. It carries derived values only: cluster count, present feature ids, access factor. Never request contents, never credentials.

Secrets: `access.credentials` and `sessionCookies` parse into memory, are never logged (there is no request-body logging at all), never cached, never echoed in responses, trace, or error paths, and go out of scope at the end of the request. The service has no persistence.

---

## The prompts

One system prompt, plus one user prompt assembled per cluster. Both live in [app/inference.py](app/inference.py).

### System prompt, verbatim

```text
You analyze captured pages from a company's website to determine which product
features the site has. You are given page excerpts and a list of feature
questions. For EVERY feature in the list you must return a verdict.

Rules:
- Judge ONLY from the provided pages. Never assume features the evidence does
  not support. Absence of evidence means present=false.
- Evidence vs speculation: a concretely named technology or visible structure
  supports an inference (a named payment provider implies its iframe), but a
  merely named-but-unshown page, step, or section does not (a wizard step
  labeled "Billing" is NOT evidence that card details are collected, because
  its contents were never captured).
- "Surfaces worth testing" means the product itself, not its public shell.
  Marketing pages, login pages, and signup wizards are the shell; their
  reachability never makes a product "publicly reachable". If the pages
  indicate the product experience requires signing in (e.g. "log in to your
  dashboard"), answer public-reachability questions present=false, even though
  the shell pages themselves loaded without credentials. Only answer
  present=true if actual product surfaces (store, app screens, content) are
  usable without any login.
- Async content loading is not client-side routing: content appearing in place
  (infinite scroll, live-updating lists, results filling in after a search) is
  DOM mutation. Judge single-page-app questions on whether navigating between
  distinct product views happens without a full page reload; distinct URLs per
  view are evidence against it.
- evidence: one short sentence citing the page (by url or sourceType) and the
  concrete wording or structure that supports your verdict. For present=false,
  say what is missing.
- confidence is one of: certain, high, likely, unsure, weak. Use "certain" only
  for explicit on-page proof; use "likely" or below for inferences (e.g. a
  payment provider implies an iframe you cannot see directly).

Return ONLY a JSON object, no prose, exactly this shape:
{"features": [{"featureId": "...", "present": true, "confidence": "high", "evidence": "..."}]}
```

### User prompt, per cluster

Assembled by `build_cluster_prompt`. One is sent per cluster, in parallel:

```text
Feature cluster: Forms & Input

FEATURES TO JUDGE:
- featureId: has-simple-forms
  question: Does the product have basic text, email, or phone input fields users fill out?
- featureId: has-multistep-forms
  question: Does the product have multi-step wizards, conditional fields, or checkout flows that span multiple pages?
...

CAPTURED PAGES:
--- url: https://acme-hr.example/login | sourceType: login | title: Sign in - Acme HR
Sign in to Acme HR. Email address. Password. Forgot your password? ...
```

### On the three calibration rules

The last three rules were added after watching real runs disagree with the worked fixtures. Each encodes a distinction the catalog's questions assume but never state: evidence versus speculation, product versus public shell, and async loading versus client-side routing. The third matters mechanically, since DOM mutation and SPA state are different capabilities, so conflating them corrupts the rollup.

With these in place, both worked fixtures reproduced their full expected capability set on live runs, including shopwave's `text-input @3 (must)`. One passing run per fixture is not evidence of stability.

**The honest caveat.** These were tuned against the only two worked examples available, which is textbook overfitting risk. I kept each rule as a generalizable distinction rather than a fixture-specific patch, and the one piece of counter-evidence I have is that the same rules also fixed two failures on the much weaker local model, which suggests they encode real distinctions rather than memorized answers. I would want to measure that rather than assert it.

## Where the toy let me cut corners

- **Evidence size.** Page text is capped at 4k characters per page, which is fine for fixtures. Production needs an extraction pass and a token budget per cluster call.
- **Catalog cache.** An unbounded in-memory dict, fine for one active version plus a few pins. Production wants an LRU bound and a metric on stale-serves.
- **Constants.** The archetype scoring weights and hint bonus, and all confidence values, are first guesses. Labeled data would calibrate them.
- **Unreachable states.** The `partial`, `mixed`, and authenticated outcomes are modeled in the schema but only reachable once live mode exists.

## With two more weeks

An eval set of labeled sites to measure feature-inference accuracy per cluster and calibrate the confidence bands. Token and cost accounting, retries with backoff on model calls, and structured logging with a redaction layer as defense in depth, since today safety comes from never logging bodies at all. Then the live crawler above, prompt caching on the evidence prefix, concurrency limits and load shedding, and contract tests run against the container in CI.

**The eighth hour** would go to the eval set. Feature-verdict accuracy is the single number this service's usefulness rests on, and nothing here measures it yet.
