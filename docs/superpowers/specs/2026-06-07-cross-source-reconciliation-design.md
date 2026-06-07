# Design — Multi-Source Cross-Reference (PRD R1)

Date: 2026-06-07
Status: roadmap step 3 of 6 (own spec per the agreed sequence).
Predecessors: R3 valuation (`2026-06-06-brain-realtime-valuation-design.md`, merged),
R6 scheduling (`2026-06-06-dynamic-scheduling-design.md`, merged).

Scope: **R1 only** — cross-reference the data sources we already have into the
agent's reasoning, and surface honest neighborhood signals. Current state 🟡:
listing data + tax-assessed value + market stats are all captured, but **not
cross-referenced**; `tax_assessed_value` and `avg_price_per_sqft` are captured
**but entirely unused**.

---

## 1. Goal

When a buyer asks "is this priced well?", don't answer from one number — **reconcile
the independent sources we hold**: the listing **asking price** (RentCast), the
county **tax-assessed value** (TCAD, via the property-record cache), Atlas's **AVM
estimate** (the brain), and the **ZIP market** (median + $/sqft + days-on-market).
Show all of them, cited, with the discrepancies called out, and derive an honest
**neighborhood signal** (e.g. "$/sqft running above the ZIP median — seller's
market") from that cached data.

This turns three captured-but-siloed sources into a single cross-checked view —
the heart of "real-time market intelligence."

## 2. Honesty constraints (project invariants, applied)

- **No live news API, no new data source.** "Multi-source" = cross-referencing the
  sources we already ingest. A live neighborhood-news feed stays a documented gap.
- **No new RentCast calls on the request path.** Reconciliation reads the DB only
  (Property, PropertyRecordCache, MarketSnapshot). Zero RentCast, trivially.
- **No fabricated numbers.** Every figure is cited to its real source with an "as of".
  When a source is missing (e.g. no tax record cached for an address), we **say so**
  and reconcile only what we have — never invent a tax value.
- **Asking ≠ sale.** Listing prices and comps are asking prices; tax-assessed is a
  government assessment (often below market); the AVM is a model estimate. Each is
  labeled as what it is; we never conflate them.

## 3. The reconciliation (Rails owns it; the brain stays pure)

A new Rails service `CrossSourceReconciliation` composes the cross-source view.
The brain remains a pure AVM (it values features+comps; it does **not** ingest tax
or market data — that Phase-2 ingestion join is out of scope here).

`CrossSourceReconciliation.for(property:, valuation:)` → a `Result` with:
- **The sources it found**, each a cited `Source(label, value, source_id, as_of)`:
  asking (listing:rentcast), AVM estimate (avm:atlas), tax-assessed (tax:tcad),
  market median + market $/sqft (market:rentcast:<zip>). Only present sources appear.
- **Cross-checks** (computed only when both operands exist):
  - `asking_vs_tax_pct` — asking vs tax-assessed.
  - `subject_ppsf` (asking ÷ sqft) and `subject_ppsf_vs_market_pct` — the home's
    $/sqft vs the ZIP market $/sqft.
- **Neighborhood signal** — `:hot` | `:balanced` | `:cool` with a one-line reason,
  derived honestly from $/sqft vs market and days-on-market (only when market data
  present). Example reasons cite the numbers ("asking $312/sqft vs $past $270 ZIP
  median; homes selling in ~18 days").
- `available?` — true when ≥2 independent sources were found (so there is something
  to reconcile); else the caller shows the single-source answer it already has.

Source lookups (DB-only, address/region keyed):
- Tax: `PropertyRecordCache` by lower(address) → `tax_assessed_value` + `captured_at`.
- Market: ZIP parsed from the property **address** (seeded regions are neighborhood
  names, ZIPs live in the address) → `MarketSnapshot` by zip; fall back to
  `MarketSnapshot` by `area == region`. Honest nil when neither matches.

## 4. Surfacing (glass box)

- **Agent price-check sidebar** (primary): the existing `_price_check` answer gains a
  **"Cross-source check"** block — a small cited table (asking / AVM / tax-assessed /
  market median + $/sqft), the asking-vs-tax and $/sqft-vs-market deltas, and the
  neighborhood-signal badge. All `respond_to?`/presence-guarded; degrades cleanly
  when a source is absent (e.g. "No county assessment on file for this address").
- **Listing page** (bonus, lighter): a compact **"Neighborhood pulse"** line from the
  market snapshot ($/sqft, days-on-market, signal) — needs no valuation, so it renders
  for any browsable listing with market data.

## 5. Demo data (offline, clearly labeled "sample")

The live tax/market path needs a RentCast key (user action, still pending), so the
seeded demo currently has **no** tax or market rows. To make R1 visible offline we
seed, with the same explicit "(sample)" provenance the curated listings already use:
- `MarketSnapshot` per seeded region (area = neighborhood; a representative zip;
  median, `avg_price_per_sqft`, `avg_days_on_market`, `new_listings`, `as_of`,
  `source: "Curated Austin sample"`).
- `PropertyRecordCache` per seeded listing with a sample `tax_assessed_value`
  (varied per listing so the asking-vs-tax delta is meaningful), `source` labeled
  "Travis County / TCAD assessment (sample)" — matching the existing sample comps.

Seeds stay **idempotent** (upsert by address/area) and **clearly labeled sample** —
consistent with the project's curated-sample, provenance-labeled approach. The real
`rake rentcast:import` / `rentcast:prewarm` path overwrites these with live data.

## 6. Components & boundaries

| Component | Lives in | Responsibility |
|---|---|---|
| `CrossSourceReconciliation` (NEW) | Rails | reconcile asking/tax/AVM/market, derive signal; DB-only |
| `PriceCheck` (extend) | Rails | attach reconciliation to its result |
| `_price_check` view (extend) | Rails | render the cross-source block + signal |
| `buyer/listings#show` + view (extend) | Rails | compact neighborhood pulse |
| `db/seeds.rb` (extend) | Rails | sample tax + market rows (labeled) |
| brain | — | **unchanged** (pure AVM; tax/market ingestion is Phase 2) |

## 7. Testing (hermetic, DB-only)

- `CrossSourceReconciliation`: all four sources present → cited sources + correct
  deltas + signal; tax missing → reconciles asking/AVM/market, no tax row, no crash;
  market missing → no signal, honest; <2 sources → `available? == false`; ZIP-from-
  address vs area fallback both resolve; signal thresholds (hot/balanced/cool).
- `PriceCheck`: result carries reconciliation; still usable when reconciliation empty.
- Agent controller/view: the cross-source block renders with citations; honest
  absent-source copy; no regression to the existing price-check assertions.
- Seeds: running seeds creates labeled sample tax + market rows; idempotent.
- Existing brain + Rails suites stay green.

## 8. Out of scope (R1)

Live neighborhood **news** feed (no API — documented gap); wiring tax-assessed value
into the **brain AVM** as a model input/anchor (Phase 2 ingestion join — the brain
stays pure here); the Go ingestion service's TCAD/GIS loaders feeding Rails (separate
unwired path); Haversine comp distances (a separate enhancement). Slot/condition
work belongs to R2.

## 9. Risks

- **Sparse demo data** → handled by §5 seeding + honest degradation; the feature is
  correct (just thinner) even with no tax/market rows.
- **Over-claiming a "signal"** from one stale snapshot → gate the signal on present
  market data, cite its `as_of`, and keep the thresholds conservative (only call a
  market hot/cool on a clear $/sqft divergence, not noise).
- **Sample data mistaken for live** → every seeded row carries a "(sample)" source
  label surfaced in the UI provenance, exactly like the curated listings/comps.
