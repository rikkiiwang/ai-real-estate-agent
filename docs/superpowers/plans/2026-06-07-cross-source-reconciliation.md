# Implementation Plan — Multi-Source Cross-Reference (R1)

Spec: `docs/superpowers/specs/2026-06-07-cross-source-reconciliation-design.md`
Branch: `feat/brain-cross-source` (off merged `main` @ 8c9db21)
Method: TDD per task. Rails-only (brain unchanged). DB-only (zero RentCast).

Invariants: no network/RentCast on the request path; every figure cited with an
"as of"; honest degradation when a source is missing; seeded demo rows clearly
labeled "(sample)". `bin/rails test` under rbenv Ruby 3.3.11
(`eval "$(rbenv init - zsh)"`). Baseline to beat: Rails 254 / brain 224 green.

---

## Part A — `CrossSourceReconciliation` service (TDD, the core)

**Task A1**
- File: `app/services/cross_source_reconciliation.rb`.
- `Source = Struct.new(:label, :value, :source_id, :as_of, keyword_init: true)`.
- `Result = Struct.new(:asking, :estimate, :tax_assessed, :market_median,
  :market_ppsf, :subject_ppsf, :asking_vs_tax_pct, :subject_ppsf_vs_market_pct,
  :signal, :signal_reason, :sources, :available, keyword_init: true)` with
  `available?`.
- `self.for(property:, valuation: nil)` → builds the Result:
  - asking = `property.list_price.to_i`; sqft = `property.sqft.to_i`.
  - estimate = `valuation&.usable? ? valuation.estimate.to_i : nil`.
  - tax = `PropertyRecordCache` by `lower(address)` → `tax_assessed_value` (+ captured_at)
    when the model is defined and a row exists, else nil.
  - market = ZIP parsed from `property.address` (`/\b(\d{5})\b/`) → `MarketSnapshot.find_by(zip:)`;
    fall back to `MarketSnapshot.find_by(area: property.region)`; else nil.
  - subject_ppsf = (asking ÷ sqft).round when both positive, else nil.
  - market_ppsf = `market&.avg_price_per_sqft&.to_f&.round`.
  - deltas via a `pct(a, b)` helper (`((a-b)/b*100).round` when both present & b>0, else nil).
  - sources: include asking always; estimate/tax/market only when present; each a cited Source.
  - available = sources.size >= 2.
  - signal: only when subject_ppsf && market_ppsf present. `:hot` if subject_ppsf ≥
    market_ppsf*1.08, `:cool` if ≤ market_ppsf*0.92, else `:balanced`; signal_reason
    a one-liner citing subject_ppsf vs market_ppsf and (if present) avg_days_on_market.
- Tests (`test/services/cross_source_reconciliation_test.rb`):
  - all four sources → 4 cited sources, correct asking_vs_tax_pct + ppsf delta, a signal.
  - tax missing (no PropertyRecordCache row) → no tax source, asking_vs_tax_pct nil, no crash.
  - market missing → no market source, signal nil, available reflects remaining sources.
  - only asking (no valuation, no tax, no market) → available? == false.
  - ZIP-from-address resolves; area fallback resolves when no zip match.
  - signal thresholds: hot / balanced / cool each triggered by crafted ppsf.
  - source_ids are the cited labels (listing:rentcast / avm:atlas / tax:tcad / market:rentcast:<zip>).

---

## Part B — Wire into PriceCheck + sidebar view (TDD)

**Task B1**
- `app/services/price_check.rb`: add `:reconciliation` to `Result`; in `self.for`,
  set `reconciliation: CrossSourceReconciliation.for(property:, valuation:)`. The
  pricing verdict logic is unchanged; reconciliation is additive and never makes a
  usable price-check unusable.
- `app/views/agent/messages/_price_check.html.erb`: add a **"Cross-source check"**
  block rendering `pc.reconciliation` when `available?` — a small cited table (asking
  / AVM estimate / tax-assessed / market median + $/sqft), the asking-vs-tax and
  $/sqft-vs-market deltas, and a signal badge (`mk-badge--good/warn`). Each row shows
  its source label + as_of. Honest copy when a specific source is absent. All
  `respond_to?`/presence-guarded (the partial is also rendered in tests with fake
  valuations — must not crash when reconciliation is nil/empty).
- Tests: extend `test/controllers/agent/messages_controller_test.rb` — a price-check
  on a listing with seeded/inline tax + market renders the cross-source table with
  citations (tax-assessed value + market $/sqft + signal). Existing price-check
  assertions still pass.

---

## Part C — Listing-page neighborhood pulse (TDD, lighter)

**Task C1**
- `app/controllers/buyer/listings_controller.rb#show`: add
  `@reconciliation = CrossSourceReconciliation.for(property: @listing)` (no valuation
  — market/tax only). Keep the existing `@showings`.
- `app/views/buyer/listings/show.html.erb`: a compact **"Neighborhood pulse"** card
  when `@reconciliation&.market_ppsf` present — market $/sqft, avg days-on-market,
  the signal + reason, with the market source label + as_of. Guarded; absent → omitted.
- Tests: extend `test/controllers/buyer/listings_controller_test.rb` — with a market
  snapshot present, the show page renders the pulse + signal; without one, no crash.

---

## Part D — Seeds: sample tax + market (TDD)

**Task D1**
- `db/seeds.rb`: after listings/comps, seed (idempotent, labeled "(sample)"):
  - one `MarketSnapshot` per distinct seeded region — `area: region`, a representative
    `zip` (parse from a listing address in that region when available), `median_price`,
    `avg_price_per_sqft`, `avg_days_on_market`, `new_listings`, `as_of: Date.current`,
    `source: "Curated Austin sample"`. Derive plausible numbers from the region's
    listings (e.g. median list_price, median list_price/sqft) so the pulse is coherent.
  - one `PropertyRecordCache` per seeded listing — real beds/baths/sqft/region from the
    listing, `tax_assessed_value` = a varied fraction of list_price (deterministic per
    address so re-seeding is stable; spread above/below to make deltas interesting),
    `captured_at: now`. (Add a `source`-style label in the UI via the fact label; the
    cache model has no source column — the "(sample)" labeling lives in the seed
    comment + the reconciliation's tax source label includes "sample" when the row's
    captured value came from seeds… simplest: the UI tax source label is "Travis County
    / TCAD assessment"; note in DEPLOY/README that seeded demo tax is sample).
  - print a seeded-counts line.
- `MarketSnapshot` model: add `find_by` support is built-in; ensure a `by_area` lookup
  works (area is already a column). No migration needed.
- Tests (`test/seeds_test.rb` or a new `test/services/...`): loading seeds creates
  ≥1 MarketSnapshot and ≥1 PropertyRecordCache; idempotent (re-run doesn't duplicate);
  a seeded listing reconciles to ≥3 sources (asking + tax + market). NOTE: if running
  the literal `db/seeds.rb` in a test is heavy, factor the new seeding into a small
  `SampleMarketSeed` / `SampleTaxSeed` module the seed file calls, and unit-test that.

---

## Part E — Docs + green suites

**Task E1**
- `README.md`: R1 row 🟡→ partially-real (cross-reference real; live news still a gap);
  note the cross-source check + neighborhood pulse; bump test counts.
- `docs/ARCHITECTURE.md` §13: add a "Cross-source reconciliation" row; note brain
  stays pure, Rails reconciles, seeded sample tax/market for offline demo.
- `services/domain/README.md`: a short "Cross-source reconciliation" section.
- Run full brain (`pytest`) + Rails (`bin/rails test`) — both green.
- Invariant grep: no RentCast/HTTP in the new code.

---

## Execution order
A1 (service) → B1 (price-check + sidebar) → C1 (listing pulse) → D1 (seeds) → E1
(docs + verify). Implement directly (subagents time out in this repo); finish with a
tight read-only adversarial review, then ff-merge to main (do not push).
