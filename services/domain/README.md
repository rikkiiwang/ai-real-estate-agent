# Domain service (Rails)

The Rails app behind `are-domain`: the **consumer marketplace** (browsable Austin
listings, passwordless visitor login, the Buyer/Seller workspaces, and the
context-aware **agent sidebar**), the **broker dashboard** (`/broker`, gated by a
server-side broker allowlist), and a **`Domain` gRPC service** the Python brain
calls (`CreateLead` / `EnqueueHandoff` / `CreateOffer`). It also owns the
append-only audit log and runs DB migrations on deploy.

See the root [`../../README.md`](../../README.md) and
[`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) for the full system.

## Run

- **Ruby:** see [`.ruby-version`](.ruby-version) (via rbenv); then `bundle install`.
- **Tests:** `bin/rails test` (SQLite — no Postgres needed). From the repo root,
  `make rails-test`.
- **Dev server:** `bin/rails server`. The agent sidebar and seller valuation call
  the brain over gRPC at `BRAIN_ADDR` (default `127.0.0.1:50151`); without a brain
  reachable they degrade gracefully.

## Sign in (passwordless)

Login is name + email, no password (a session identity for context, not a
security boundary). To reach the broker dashboard, sign in with an email on the
broker allowlist — the config default is `broker@atlas.example`, extended via the
`BROKER_EMAILS` env var. Any other email is an ordinary buyer/seller visitor.

## Configuration

- `BRAIN_ADDR` — brain gRPC address for orchestrate / valuation / contract draft.
- `BROKER_EMAILS` — comma-separated emails allowed into the broker dashboard,
  extending the config default in [`config/marketplace.yml`](config/marketplace.yml).
- `RENTCAST_API_KEY` — enables `rake rentcast:import` (real listing + market data)
  and `rake rentcast:prewarm` (see below); unset, the app falls back to the seeded
  sample listings.
- **Channel transport (optional)** — the Ask Atlas sidebar's SMS/Email channels run on
  a `Simulated` transport (`app/services/channel_transport.rb`) unless a provider is
  configured. Set `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` (SMS) or `SENDGRID_API_KEY`
  (email) to auto-engage the real `TwilioSms` / `SendgridEmail` adapters; unset, the
  agent still replies in-thread and shows a `simulated` delivery note. Voice & Chat
  need no configuration.

## Valuation & RentCast quota

The valuation request path (seller workspace + buyer agent sidebar) reads the DB
only — it never calls RentCast during a web request. Freshness comes from the
`MarketSnapshot` table (written by `rake rentcast:import`); comparable listings
come from the `Property` pool (active listings imported by the same task).

For arbitrary typed addresses (addresses not yet in the browsable catalog), run
the capped pre-warm task once after an import:

```bash
# Warm up to 25 addresses (each unique address costs at most 1 RentCast call;
# already-cached rows are skipped without a call).
rake rentcast:prewarm ADDRESSES='123 Main St, Austin TX;456 Oak Ave, Austin TX' MAX_CALLS=25

# Warm all un-cached browsable listings up to a cap:
rake rentcast:prewarm MAX_CALLS=50
```

The `PropertyRecordCache` table stores the result (real beds/baths/sqft/geo/tax);
`SubjectResolver` reads it. The demo is pre-warmed for the seeded listings, so
the live site and demo spend **zero RentCast calls** during normal use.

## Cross-source reconciliation (R1)

`CrossSourceReconciliation.for(property:, valuation:)` reconciles the independent
sources we already hold — **asking price** (listing), **county tax assessment**
(`PropertyRecordCache.tax_assessed_value`), **AVM estimate** (brain), and the
**ZIP market** (`MarketSnapshot`: median + `avg_price_per_sqft` + days-on-market)
— into one cited view plus an honest neighborhood signal (hot / balanced / cool,
from $/sqft vs the ZIP market). DB-only (zero RentCast); a missing source is
reported, never invented. Rails owns this; the brain stays a pure AVM.

- Surfaced in the **agent price-check sidebar** (a "Cross-source check" block) and
  a listing-page **"Neighborhood pulse"** card.
- Market lookup: ZIP parsed from the property address → `MarketSnapshot` by zip,
  falling back to a snapshot keyed by the region name.
- Offline demo data: `SampleCrossSourceSeed` (run by `db/seeds.rb`) seeds labeled
  **"(sample)"** per-ZIP market snapshots + per-listing tax assessments so the
  cross-source view demos without a RentCast key; the real `rentcast:import` /
  `rentcast:prewarm` path overwrites them with live data.

## Visual property analysis (R2)

Listing photos are analyzed by **Claude vision** (in the brain) into structured,
image-cited findings. Value-features feed the AVM's photo-derived `condition` and
show on the listing as "What the photos show"; red-flags route to a **broker-only**
review queue and are never shown to buyers.

- `PhotoAnalysis` cache (condition + findings + needs_review + provenance) is read on
  the request path — **zero Anthropic calls on a web request** (like the RentCast path).
- `rake vision:analyze MAX_CALLS=25` (capped, cache-first) is the only Anthropic spend.
  It needs `ANTHROPIC_API_KEY` set **on the brain** (`fly secrets set ANTHROPIC_API_KEY=…
  --app are-brain`); without it the brain returns a deterministic fake analysis.
- Offline demo: `SampleVisionSeed` (run by `db/seeds.rb`) writes labeled "(sample)"
  `PhotoAnalysis` so the panel + condition demo with no key; `vision:analyze` overwrites
  with real Claude analysis. `ValuationAssembly` reads the cached condition into the
  existing `PropertyFeatures.condition` (no GetValuation proto change).

## Ask Atlas suggested prompts + buyer profile

The buyer listing page stays lean (photos, price, facts, offer, schedule). Listing
**analysis is answered on demand by Ask Atlas** via suggested-prompt chips — "Is
this fairly priced?" (`PriceCheck` + cross-source), "How's this neighborhood?"
(`CrossSourceReconciliation`), "What do the photos show?" (`PhotoAnalysis`
**feature findings only** — red-flags stay broker-only), "Can I tour this week?"
(`ShowingScheduler`). Each chip POSTs an explicit `insight` key that
`Agent::MessagesController` routes to a deterministic, DB/cache-read answer (zero
external calls); free text still falls through to the brain orchestrator.

Buyer qualification lives on the **buyer profile** (`/buyer/profile`:
pre-approval / move-in timeline / budget), edited after the passwordless sign-in.
Saving runs `IntentTriage` (R5) and routes a high-intent lead to the broker; the
old per-message sidebar checkboxes are gone.

## Dynamic scheduling (tours / inspections)

A real collision-avoidance engine — DB-only, no external calendar, no network.

- **`Appointment`** model — a requested/confirmed showing occupying a half-open
  `[starts_at, ends_at)` slot on a property (and optionally a broker). `active`
  (requested+confirmed) rows occupy slots; `declined`/`cancelled`/`completed`
  free them. A `validate :no_active_double_booking, on: :create` race-guard
  rejects overlapping active rows.
- **`ShowingScheduler`** — `available_slots(property:, now:, broker_email:, kind:)`
  generates business-hours slots (30-min, 9–18, 7-day horizon) and subtracts past
  times, property + broker double-bookings, and blacked-out (under_offer/sold/
  retired) listings; `slot_free?(...)` is the commit-time re-check. **`now` is
  injected — the algorithm never reads the wall clock**, so it is deterministic.
- **`ShowingIntent`** — Rails-side mirror of the brain's
  `scheduling.classify_scheduling_intent`; lets the agent sidebar answer "can I
  tour this Friday?" with real openings.

Routes:

```
POST /buyer/listings/:listing_id/showings          # buyer requests a slot (public)
POST /broker/appointments/:id/confirm              # broker confirms (re-checks collision)
POST /broker/appointments/:id/decline              # broker declines
```

Booked slots are surfaced on the listing page and in the agent sidebar; the
broker's dashboard has a **Pending showings** confirm/decline queue. Every
transition is written to the append-only audit log.
