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
- `RENTCAST_API_KEY` — enables `rake rentcast:import` (real listing + market data);
  unset, the app falls back to the seeded sample listings.
- **Channel transport (optional)** — the Ask Atlas sidebar's SMS/Email channels run on
  a `Simulated` transport (`app/services/channel_transport.rb`) unless a provider is
  configured. Set `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` (SMS) or `SENDGRID_API_KEY`
  (email) to auto-engage the real `TwilioSms` / `SendgridEmail` adapters; unset, the
  agent still replies in-thread and shows a `simulated` delivery note. Voice & Chat
  need no configuration.
