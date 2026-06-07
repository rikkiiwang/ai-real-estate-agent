# Design — Visual Property Analysis (PRD R2)

Date: 2026-06-07
Status: roadmap step 4 of 6 (own spec). Predecessors merged: R3, R6, R1.
Decision (user): the vision model is **Claude** (Anthropic), not Gemini.

Scope: **R2 only** — analyze listing photos into structured, image-cited findings,
feed a photo-derived **condition** signal into the AVM, and surface the findings in
the glass box. Current state 🟡: the brain's `vision/` module (schema + analyzer +
`VisionModel` protocol + `FakeVisionModel`) is real and tested, but there is **no
real model implementation, no prod wiring, and no UI** — and the AVM's `condition`
input is always imputed.

---

## 1. Goal

For a listing's photos, produce structured findings — value `feature`s (e.g.
`updated_kitchen`, `hardwood_floors`) and `red_flag`s (visible defects) — each cited
to a specific photo with a confidence. Turn the features into a real **condition
score** that feeds the existing AVM `condition` input (replacing the imputed
default and tightening the band). Surface the features to buyers as cited evidence;
route red-flags / low-confidence findings to a human (never assert a defect to a
buyer). Powered by **Claude vision**, with a deterministic fake fallback so the
system runs (and demos) with no API key.

## 2. Honesty + quota invariants (same as R3/R1)

- **The request path makes ZERO Anthropic calls.** Vision is computed by a capped,
  cache-first `rake vision:analyze` task and **cached** (condition + findings in the
  DB); the live valuation/UI read the cache only — mirroring `rentcast:prewarm`.
- **Key-gated, hermetic fallback.** `ANTHROPIC_API_KEY` unset → the deterministic
  `FakeVisionModel`/sample path runs; tests + offline demo work with no key. Setting
  the key activates real Claude.
- **No fabricated claims.** Findings cite a real photo + confidence. `red_flag`s and
  sub-threshold findings are **never** shown to a buyer as claims — they go to human
  review (the broker handoff), exactly as `analyzer.py` already enforces.
- **Labeled provenance.** Cached analysis records whether it came from real Claude
  vision or the sample/fake path; the UI shows it (like the "(sample)" listings/tax).

## 3. The Claude vision model (brain)

`ClaudeVisionModel` — a new `VisionModel` implementation, sibling to the existing
`GeminiVisionModel`, mirroring the `llm.py`/`GeminiClient` conventions (stdlib
`urllib`, key-gated factory, circuit breaker) so the brain stays dependency-free.

- Calls the Anthropic Messages API (`POST /v1/messages`, headers `x-api-key` +
  `anthropic-version: 2023-06-01`) with the photo as a base64 `image` block and a
  forced `tool_choice` over the existing `FINDINGS_FUNCTION_SCHEMA["parameters"]`
  (as the tool `input_schema`) — structured output only, never prose. Parses the
  `tool_use` block's `input["findings"]`.
- Model id: default `claude-opus-4-8`, overridable via `ANTHROPIC_MODEL` (mirrors
  `GEMINI_MODEL`). No `temperature`/`top_p`/`top_k` (removed on Opus 4.8). Media type
  sniffed from the image bytes (JPEG/PNG), default jpeg.
- `claude_vision_model_or_none()` returns a `ClaudeVisionModel` only when
  `ANTHROPIC_API_KEY` is set, else `None` (→ caller uses `FakeVisionModel`).
- Circuit breaker (cooldown after an HTTP failure) like `llm.py`, so a bad/quota'd
  key never adds latency to the (capped) task.

**Condition derivation** — `condition_from_findings(features, red_flags) -> float`
in `[0, 1]`: a deterministic mapping (base 0.5, positive features raise it weighted
by confidence, red-flags lower it), clamped. Pure, unit-tested. Feeds the AVM's
existing `condition` input.

## 4. The AnalyzePhotos seam (brain RPC)

New `Vision` service RPC `AnalyzePhotos(AnalyzePhotosRequest{repeated photo_url,
address}) -> AnalyzePhotosResponse{repeated Finding findings, double condition,
repeated Finding needs_review, string provenance}`.

- Servicer fetches each photo URL → bytes (urllib; this is the capped task path, not
  the request path), runs `PhotoAnalyzer` over them with the available model
  (`claude_vision_model_or_none()` else `FakeVisionModel`), and returns the analyzer's
  `features` (→ findings), `red_flags` + low-confidence (→ needs_review), the derived
  `condition`, and a `provenance` ("claude" | "fake"). Corrupt/missing photos are
  recorded, never crash the batch (the analyzer already does this).
- The brain stays pure compute: it fetches photos only inside this explicit task RPC;
  the valuation request path never calls it.

## 5. Rails: cache, capped task, valuation wiring

- **`PhotoAnalysis` cache** (NEW model + migration + hand-edited schema.rb): per
  `property` (or address) → `condition` (decimal), `findings` (json), `needs_review`
  (json), `provenance` (string), `analyzed_at`. TTL-style freshness like
  `PropertyRecordCache`.
- **`rake vision:analyze`** (capped, cache-first, like `rentcast:prewarm`): for each
  browsable listing missing/stale analysis, call `Vision.AnalyzePhotos` with the
  listing's `photo_urls`, cache the result. Hard `MAX_CALLS` budget; logs spend;
  skips fresh rows. This is the ONLY path that spends Anthropic budget.
- **Valuation wiring (request path, DB-only):** `SubjectResolver`/`ValuationAssembly`
  reads the cached `PhotoAnalysis.condition` and passes it through the **existing**
  `PropertyFeatures.condition` field — so the AVM uses the real photo-derived
  condition with **no proto change to GetValuation** and no Anthropic call.
- **Brain RPC client** (`BrainVisionClient`, Rails) used only by the task.

## 6. UI surfacing (glass box)

- **Listing page + price-check**: a **"What the photos show"** panel listing the
  cited `feature` findings (label + confidence + which photo), and the photo-derived
  condition as a valuation driver (the price-check already renders
  `Photo-derived condition score`; it becomes a real cited contribution instead of
  "imputed"). Provenance line ("Claude vision" or "sample").
- **Red-flags → human, not buyer**: any `needs_review` findings are surfaced to the
  **broker** (dashboard), never asserted to the buyer — consistent with HITL.
- Honest empty-state when no analysis is cached ("Photo analysis not yet run").

## 7. proto / model / data changes

- **proto**: add a `Vision` service + `AnalyzePhotos` RPC + `Finding` message
  (kind/label/confidence/evidence_photo_id/optional bbox). **No change to
  `GetValuation`** — condition flows through the existing `PropertyFeatures.condition`.
- **brain**: `vision/model.py` gains `ClaudeVisionModel` + `claude_vision_model_or_none`;
  a `vision/condition.py` (or analyzer helper) for `condition_from_findings`; a
  `VisionServicer` in `server.py`.
- **Rails**: `PhotoAnalysis` model + migration + schema.rb edit; `BrainVisionClient`;
  `rake vision:analyze`; `ValuationAssembly` reads cached condition; views; sample seed.

## 8. Offline demo data

Like R1's sample seeds: `SampleVisionSeed` (run by `db/seeds.rb`) writes labeled
**"(sample)"** `PhotoAnalysis` rows (a couple of plausible features + a condition)
per seeded listing, so the "What the photos show" panel + condition driver demo
without an `ANTHROPIC_API_KEY`. The real `rake vision:analyze` overwrites them.

## 9. Testing (hermetic)

- `ClaudeVisionModel.build_request` shape (forced tool, base64 image, model id, no
  sampling params); response parse pulls `findings` from the `tool_use` block; a fake
  HTTP transport drives `analyze_photo` with no network.
- `claude_vision_model_or_none()` key-gating.
- `condition_from_findings`: features raise, red-flags lower, clamped to [0,1],
  deterministic.
- `AnalyzePhotos` servicer with `FakeVisionModel` (no key) → findings + condition +
  provenance="fake"; corrupt photo handled.
- Rails: `PhotoAnalysis` model; `vision:analyze` task is capped + cache-first;
  `ValuationAssembly` passes cached condition into features; views render the panel +
  route red-flags to the broker; `SampleVisionSeed` idempotent + labeled.
- Existing brain + Rails suites stay green.

## 10. Out of scope (R2)

Real listing photos beyond the seeded sample imagery; bounding-box overlays in the
UI; running vision inside the live orchestrator turn (it's a cached task); training
the AVM on condition (the model already consumes `condition` — we only populate it).
SMS/email (R4, last).

## 11. Risks

- **Cost** — Opus vision per photo across listings. Mitigation: the task is hard-capped
  (`MAX_CALLS`) + cache-first; default model overridable via `ANTHROPIC_MODEL`; the
  request path spends nothing.
- **Photo realism** — seeded photos are sample/Unsplash; real Claude analysis of them
  is honest about *those* images. Labeled provenance avoids over-claiming.
- **Defect liability** — red-flags must never reach the buyer as claims; enforced by the
  analyzer's existing `red_flag` → `needs_review` routing + the broker-only surface.
