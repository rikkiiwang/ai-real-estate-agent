# Implementation Plan — Visual Property Analysis (R2)

Spec: `docs/superpowers/specs/2026-06-07-visual-property-analysis-design.md`
Branch: `feat/brain-vision` (off main @ 35d8db1)
Method: TDD. Vision model = **Claude** (Anthropic), key-gated, fake fallback.

Invariants: request path makes ZERO Anthropic calls (cached, capped task spends
budget); `ANTHROPIC_API_KEY` unset → deterministic fake/sample path; red-flags never
shown to buyers (→ broker); labeled provenance. brain tests via
`PYTHONPATH=src python3 -m pytest`; Rails via rbenv Ruby 3.3.11 + `bin/rails test`.
Baseline: brain 224 / Rails 268 green.

---

## Part A — Brain: ClaudeVisionModel + condition derivation (Python, TDD)

**A1 — `ClaudeVisionModel`** in `services/brain/src/brain/vision/model.py` (sibling to
`GeminiVisionModel`):
- `build_request(image_bytes, ref)` → Anthropic Messages body: `model` (env
  `ANTHROPIC_MODEL`, default `claude-opus-4-8`), `max_tokens`, `tools=[{name:
  report_property_findings, description, input_schema: FINDINGS_FUNCTION_SCHEMA["parameters"]}]`,
  `tool_choice={type: tool, name: report_property_findings}`, `messages=[{role: user,
  content: [image base64 block (media_type sniffed), text instruction]}]`. No
  temperature/top_p/top_k.
- `analyze_photo(image_bytes, ref)` → POST via stdlib urllib with headers `x-api-key`,
  `anthropic-version: 2023-06-01`, `content-type`; circuit breaker (module cooldown
  after HTTP error, like `llm.py`); parse the `tool_use` block whose name matches →
  `input["findings"]` (defensive, structure-only; never read prose). Requires injected
  client/key; raises if absent (caller uses Fake).
- `_sniff_media_type(image_bytes)` → "image/png" for `\x89PNG`, else "image/jpeg".
- `claude_vision_model_or_none()` factory: returns `ClaudeVisionModel` when
  `ANTHROPIC_API_KEY` set, else None.
- Export from `vision/__init__.py`.

**A2 — `condition_from_findings`** in `services/brain/src/brain/vision/condition.py`:
- `condition_from_findings(features, red_flags) -> float`: base 0.5; each feature adds
  `+w*confidence` (small w, e.g. 0.08); each red_flag subtracts `-w2*confidence`
  (larger w2, e.g. 0.15); clamp [0,1]. Deterministic, pure.

**Tests** (`services/brain/tests/test_claude_vision.py`, `test_condition.py`):
- request shape: forced tool, base64 image block, model id honored from env, sniffed
  media type, no sampling params.
- response parse: extracts `findings` from a fake tool_use response; empty/no-tool →
  `[]`; never reads prose text.
- a fake HTTP transport drives `analyze_photo` end-to-end with no network.
- `claude_vision_model_or_none()` None without key, instance with key.
- `condition_from_findings`: features raise, red_flags lower, clamp [0,1], deterministic.

---

## Part B — Brain: AnalyzePhotos RPC (proto + servicer, TDD)

**B1 — proto** `proto/realestate/v1/realestate.proto`: add
- `message VisionFinding { string kind; string label; double confidence; string evidence_photo_id; }`
- `message AnalyzePhotosRequest { string address; repeated string photo_urls; }`
- `message AnalyzePhotosResponse { repeated VisionFinding findings; double condition; repeated VisionFinding needs_review; string provenance; }`
- `service Vision { rpc AnalyzePhotos(AnalyzePhotosRequest) returns (AnalyzePhotosResponse); }`
- Regenerate Go/Python/Ruby stubs (`make proto`, honoring `PYTHON=`). **No change to GetValuation.**

**B2 — `VisionServicer`** in `services/brain/src/brain/server.py`:
- For each photo_url: fetch bytes (urllib GET, short timeout, skip on error). Build
  `PhotoRef`s. Run `PhotoAnalyzer(model)` where `model = claude_vision_model_or_none()
  or FakeVisionModel(...)`. Map `AnalysisResult.features` → findings,
  `red_flags`+below-threshold → needs_review, `condition_from_findings(...)` → condition,
  provenance = "claude" if real model else "fake". Register servicer in `build_server`.
- Tests (`services/brain/tests/test_vision_servicer.py`): with FakeVisionModel canned
  findings (monkeypatch the factory to None + inject fake via analyzer seam, or pass a
  fake fetcher) → response carries findings + condition + provenance="fake"; a
  failing/unfetchable URL is skipped, batch still returns.

---

## Part C — Rails: PhotoAnalysis cache + capped vision:analyze task (TDD)

**C1 — model + migration** `PhotoAnalysis`: `property_id` (fk), `address`, `condition`
(decimal), `findings` (json, default []), `needs_review` (json, default []),
`provenance` (string), `analyzed_at`; index on property_id/address. Migration
`20260607000001_create_photo_analyses.rb` + hand-edit `db/schema.rb` (bump version).
`fresh?` (TTL). Tests: validations, fresh?, scopes.

**C2 — `BrainVisionClient`** (Rails gRPC client for `Vision.AnalyzePhotos`), degrades
gracefully when brain unreachable (like `BrainValuationClient`). Inject fake stub in tests.

**C3 — `rake vision:analyze`** (`lib/tasks/vision.rake`): cache-first, hard `MAX_CALLS`
cap, logs spend, skips fresh; calls `BrainVisionClient` per browsable listing with
`photo_urls`; upserts `PhotoAnalysis`. Tests via a fake client: capped + cache-first +
upsert (mirror the rentcast prewarm test).

---

## Part D — Rails: valuation wiring + UI (TDD)

**D1 — feed cached condition into the AVM**: `ValuationAssembly` (or `SubjectResolver`)
reads `PhotoAnalysis.condition` for the subject and threads it into the features hash
so `BrainValuationClient#build_features` sets `PropertyFeatures.condition` /
`has_condition`. Request path: DB-only, no Anthropic. Test: a cached analysis makes the
valuation send a real condition (assert on the fake valuation client's received features).

**D2 — UI**: a **"What the photos show"** partial on the listing page (+ price-check
sidebar) listing cited feature findings (label, confidence, photo) + provenance, and the
photo-derived condition as a driver. Broker dashboard: a **"Flagged for review"** section
from `needs_review` (never shown to buyers). Honest empty-state. Tests: listing/price-check
render features (not red-flags); broker dashboard shows needs_review; buyer never sees a red_flag.

---

## Part E — Seeds + docs + green suites

**E1 — `SampleVisionSeed`** (run by `db/seeds.rb`): labeled "(sample)" `PhotoAnalysis`
per seeded listing (a couple plausible features + a condition + provenance "sample").
Idempotent. Test: creates rows, idempotent, a seeded listing reconciles to a condition.

**E2 — docs + verify**: README R2 row → real (Claude vision, cached, key-gated); how to
set `ANTHROPIC_API_KEY` + run `rake vision:analyze`; ARCHITECTURE §13 vision row; domain
README vision section; bump test counts. Run full brain + Rails suites green. Invariant
grep: no Anthropic/HTTP call on the request path (only in `ClaudeVisionModel` + the
servicer fetch + the task).

---

## Execution order
A (model+condition) → B (RPC+servicer) → C (cache+task) → D (wiring+UI) → E (seeds+docs).
Implement directly (subagents time out); finish each part green + committed; tight
read-only adversarial review before ff-merge to main (do not push).
