# Design — Real-Time Valuation (PRD R3), and the surrounding roadmap

Date: 2026-06-06
Status: approved (design), pending written-spec review
Scope of THIS spec: **R3 only** (Predictive / Real-Time Valuation). The other
requirements below are recorded for context and are each their own spec later.

---

## 0. Context — full PRD functional-requirement audit (evidence-based)

This work started from "the core Brain isn't complete enough." We audited all 12
functional requirements against the actual code. Legend: 🟢 real · 🟡 partial/seam · 🔴 absent.

| # | Requirement | Status | Gap |
|---|---|---|---|
| R1 | Multi-source ingestion + cross-reference | 🟡 | listings real, TCAD/GIS real but **not cross-referenced** with listings; **news absent** |
| R2 | Visual property analysis (photos) | 🟡 | schema/analyzer/Gemini request real but **never run in prod**, no client, no real photos |
| R3 | Predictive / real-time valuation | 🟡 | real model, but **synthetic training + address-hash features + no recency** ← THIS SPEC |
| R4 | Omnichannel (voice/SMS/email, one thread) | 🟡 | voice input real; **SMS/Email simulated** (accepted as a labeled seam) |
| R5 | Intent triaging | 🟢 | fully wired to broker dashboard |
| R6 | Dynamic scheduling (tours/inspections) | 🔴 | **zero code** — the biggest hole |
| R7 | TREC document generation | 🟢 | deterministic form-fill, UPL-guarded, gRPC-wired |
| R8 | Automated negotiation | 🟢 band / 🟡 loop | authorized band real; **no auto-counter-response loop** |
| R9 | Closing orchestration | 🟡 | milestone routing real, **sinks NotImplementedError, not wired into prod graph** |
| R10 | Fair Housing compliance | 🟢 | deny-list + neutral allow-list, wired |
| R11 | Critic truth-verification | 🟢 | gates every send, wired |
| R12 | HITL triggers | 🟢 | sentiment + confidence triggers, wired |

The entire **Lawyer** pillar (R10–R12) and intent triaging (R5) + TREC (R7) are
genuinely real. The work ahead closes the partial/absent items.

### Agreed sequence (each its own spec → plan → implementation)

1. **R3 real-time valuation** ← this spec
2. R6 dynamic scheduling (absent → build)
3. R1 cross-source + neighborhood-signal feed
4. R2 photo visual analysis (needs Gemini key)
5. R9 closing-orchestration wiring + R8 counter-offer loop
6. R4 SMS/Email (fixed last)

### Hard constraints (apply to every pillar)

- **No real MLS feed; no live news API.** RentCast (a third-party listing-data
  aggregator) is our real source; it refreshes ~daily ("500k updates/day"), **not**
  a literal real-time stream.
- **RentCast quota is precious.** Free tier (50/mo) is exhausted; we are upgrading
  to a paid tier (Foundation $74/mo = 1,000 req, or higher). **Minimize calls.**
- **Invariant (preserved): the live site / demo NEVER calls RentCast.** All request-path
  reads are DB-served. RentCast is touched only by an explicit, rate-capped pre-warm/refresh job.

---

## 1. R3 Goal

Turn valuation from "real algorithm fed fake inputs, static" into a genuinely
**data-grounded, freshness-aware** estimate for any Austin address, where every
number is cited to a real source, and the output honestly reflects recent market
activity to the cadence our data supports.

Non-goal: a literal per-second live AVM, or retraining the model on real MLS sale
prices (we don't have sale labels; listings are asking prices).

## 2. Approved approach — comps-anchored + model-as-adjuster + recency

Chosen over (a) retraining on real data (quota-heavy, weak labels, not "real-time")
and (b) just swapping in real features with no comp anchor (absolute price level
unreliable from a synthetic-trained model).

- **Real comps anchor the price level** — nearby, similar, recency-weighted listings
  from our cached pool set the baseline.
- **The existing ML model (sklearn GBM) provides per-feature adjustments + explanation**
  (the signed dollar `contribution` per feature already exists).
- **A light, honest calibration** scales the synthetic-trained model's price level to
  the real-market median observed in the cached pool (single multiplicative factor,
  fit offline, stored — not on the request path).
- **Recency** weights recent comps higher and surfaces a real "recent activity" summary.

## 3. Components & boundaries

| Component | Lives in | Responsibility | Depends on |
|---|---|---|---|
| `RentCastClient` (extend) | Rails domain | **Only thing that calls RentCast.** Add `property_record(address)`; reuse `sale_listings`. | RentCast API key |
| Cache: `Property` (expand) | Rails | the real listing pool (comp source) | RentCast import job |
| Cache: `PropertyRecord` (NEW) | Rails | per-address real attributes + tax-assessment + sale history, keyed by normalized address, `captured_at` + TTL | RentCast import job |
| `CompsSelector` (NEW) | Rails | given a subject (attrs + ZIP/geo), pick K similar from the cached pool, weight by similarity × recency | cache only (no network) |
| `ValuationAssembler` (NEW) | Rails | build the gRPC payload (real features + comps + market snapshot + recency window) and call brain | CompsSelector, cache |
| `GetValuation` (extend) | brain (Python) | accept real features + comps; estimate with real features; return estimate + bands + per-feature contributions + recency note | calibration factor |
| Critic citations | brain | bind each fact to a real comp / record id | existing Critic |

Boundary rules:
- The **request path reads cache only**; it never calls RentCast.
- **brain stays pure compute** — it receives features/comps, never fetches them.
- RentCast access is funneled through `RentCastClient` exclusively.

## 4. Cache & quota strategy (the load-bearing constraint)

- **Pre-warm/refresh rake task** (run manually by us, off the request path):
  - Listings: 1 bulk request per ZIP (returns many) across the 10–12 Austin ZIPs ⇒ ~12 requests refills the whole comp pool, incl. `daysOnMarket` / list date / price changes.
  - Property Records: 1 request **per address** ⇒ only fetched for a **bounded curated demo-address set**, never per browse.
  - A hard `MAX_RENTCAST_CALLS` budget; the task **logs how many calls it made and refuses to exceed** the cap.
  - Cache-first: skip any address/ZIP whose cached `captured_at` is within TTL.
- **Comps are computed locally** from the cached pool, so valuing any subject in a
  covered area costs **0 RentCast calls**.
- Net effect: a full refresh costs a few dozen calls/month; **demo and live = 0 calls.**

## 5. Honest "real-time / last-24h" definition

- **Freshness label**: surface the cache `captured_at` as "data as of <time>", and the
  true cadence ("updated ~daily"). No faked live stream.
- **Recent activity summary**: derived from the cached pool — new listings + price
  changes within a window (configurable, e.g. 7/30 days) for the subject's ZIP, plus
  the ZIP market-snapshot trend. Reported as cited facts.
- If the only honest statement is "no qualifying recent activity in window," say that
  (consistent with the glass-box "no source → no claim" rule).

## 6. proto / model / data changes

- **proto** (`proto/realestate/v1/realestate.proto`): extend `GetValuationRequest`
  with optional `PropertyFeatures features` (beds, baths, sqft, year_built, lot_sqft,
  condition, lat, lng) and `repeated Comp comps` (id, price, sqft, beds, baths,
  distance, age_days/list_date). **Keep the address-only path** as a documented
  fallback when no real features are available (current hash-derived behavior).
- **brain** (`valuation/features.py`): `derive_record(address, real_features=None)` —
  use real features when present, else hash fallback. `valuation/model.py`: apply the
  stored calibration factor; comps-anchor the final estimate; bands from comps
  dispersion + model quantiles. `valuation/schema.py`: add `as_of` timestamp +
  `recent_activity` summary + `source` per fact.
- **Rails data model**: new `PropertyRecord` (cache) migration; `Property` gains/uses
  recency fields already available from listings (`daysOnMarket`, list date, price
  history) if not already stored. Migrations are hand-edited into `db/schema.rb` for
  local SQLite tests (local Postgres not running), per existing project practice.

## 7. UI surfacing (glass box)

Seller valuation + buyer agent sidebar show: the estimate + band, **"data as of <time>"**,
the **recent-activity line**, the **comps used** (cited, clickable), and the existing
**per-feature dollar drivers** panel — all grounded, nothing un-cited.

## 8. Testing strategy (hermetic)

- Fixture cached listings + a **fake RentCast client**; assert the **request path makes
  zero network calls** (cache-only).
- `CompsSelector`: deterministic selection + recency/similarity weighting.
- Recency window logic (in-window vs none → honest "no activity").
- Real-features valuation path vs hash fallback path.
- Calibration factor applied; bands ordered (low ≤ est ≤ high).
- proto round-trip (features + comps populate; address-only fallback still works).
- Pre-warm task respects `MAX_RENTCAST_CALLS` and is cache-first (skips fresh entries).
- Existing brain + Rails suites stay green.

## 9. Dependencies & risks

- **Dependency (user action)**: RentCast paid upgrade + new key placed in
  `deploy.env` / Fly secrets. Design + hermetic tests proceed without it; only the
  one-time pre-warm needs the live key.
- **Risk**: thin comp coverage for a typed address outside covered ZIPs → fall back to
  the address-only model path and **label lower confidence** (honest), rather than fake a comp.
- **Risk**: asking prices ≠ sale prices → never call a comp a "sale"; label it
  "active listing" and anchor accordingly.

## 10. Out of scope (R3)

Cross-referencing tax-assessed value into the agent's reasoning (that's R1), photo
findings (R2), and any literal sub-daily live feed.
