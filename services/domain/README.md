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
