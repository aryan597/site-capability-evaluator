# Loom outline (target ≤ 9 min)

Not part of the submission docs — these are recording notes. Speak it, don't read it.

## Before recording

- Terminal 1: `uvicorn mock_catalog.server:app --port 9001`
- Terminal 2: `set CATALOG_BASE=http://127.0.0.1:9001` + your `ANTHROPIC_API_KEY`, then `uvicorn app.main:app --port 8000`
- Terminal 3 ready with the curl command; editor open on `app/rollup.py` and `fixtures/sites/shopwave.expected.json`.

## 1. Demo first (~2 min)

- "This service answers one question: what would our agent need to test this site — never whether our agent is good enough. That scoring is out of scope by design."
- Fire the request: `curl -s -X POST http://127.0.0.1:8000/v1/evaluate -H "Content-Type: application/json" -d @fixtures/sites/acme-hr.input.json`
- Walk the response top-down: archetype, a couple of inferredFeatures with their evidence lines, requiredCapabilities, `accessOutcome: "public-only"` — "the product is gated, and that's a 200, not an error; it just lowers confidence."

## 2. The fuzzy/deterministic boundary (~1.5 min)

- "The LLM answers exactly one kind of question: is this feature present on these pages. It picks a confidence *word*, not a number. Everything numeric — the rollup, archetype scoring, confidence math — is plain code."
- Show `app/rollup.py`: "pure function, no LLM, no I/O — this is the graded part."
- State the rollup rule from memory (you answered this correctly in review): level = max across demands, criticality = strictest, **independently** — show shopwave's `text-input`: level 3 comes from a *should* demand, *must* comes from level-2 demands ⇒ `@3 must`.

## 3. LLM at scale (~1.5 min)

- "Real catalog is ~70 features, ~155 capabilities. I batch one call per feature *cluster*, in parallel: prompt size stays bounded as the catalog grows, latency stays about one call, cost is ~10 calls not 70."
- "The 155 capabilities never appear in any prompt — they're resolved deterministically, so catalog growth on the capability side is free."
- Mention the rejected options and why: mega-prompt (attention cliff), per-feature (linear cost/latency).

## 4. Determinism & testing (~1.5 min)

- "My claim is precise: the service adds zero nondeterminism of its own. In CI the LLM seam is a scripted fake and the test asserts *byte-identical* responses — run `python -m pytest tests/ -q` on camera."
- "Against the real LLM: temperature 0, pinned model, word-bands — a borderline wobble rarely flips a band where it would always flip a float. The residual risk lives only at the seam, and that's stated tolerance, not a flaky test."

## 5. Live investigation design (~1.5 min)

- "v1 is pass-in only — a domain-only request gets an honest 501. Here's what I'd build:" adaptive crawl — homepage first, then a *cheap* model decides which link is worth fetching next given the unanswered feature questions, under hard page/time budgets.
- Gated site: "the login wall is itself evidence — then pivot to pricing, docs, signup structure, third-party listings; report public-only and let the access factor lower overall confidence — that part is already implemented."
- Bounds: robots.txt, rate limits, GET-only, and never real logins against third-party IdPs.

## 6. Two more weeks (~1 min)

- Eval set of labeled sites to *measure* feature-inference accuracy — "the one number the service's usefulness hangs on; it's where my 8th hour goes."
- Cost/token accounting, retries, redaction-layer logging, then the live crawler.
- Worry list: confidence constants are uncalibrated first guesses (structure is right, numbers need data); evidence size at production needs an extraction pass.
