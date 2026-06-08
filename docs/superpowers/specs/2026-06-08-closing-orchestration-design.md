# Closing Orchestration Wiring — Design

Date: 2026-06-08
Status: Approved (brainstorm) — pending spec review
Cluster: 2 (closing orchestration #9). Decided: **Full** scope (broker buttons +
inspection auto-link + buyer-visible tracker); **extend the `Closer` service**;
**enforce milestone order**.

## Problem

The Python `ClosingOrchestrator` (`services/brain/src/brain/orchestrator/closing.py`)
is fully built and tested — four milestones (`inspection_cleared →
earnest_deposited → title_cleared → funded`), a milestone→counterparty routing
table (escrow / title / lender), and idempotent ping emission — but it is
**completely unwired**: no gRPC RPC exposes it, no Rails model tracks closing
state, no broker action records a milestone. `GrpcCounterpartySink` deliberately
raises ("documented seam"). This is functional-requirement #9 (Closing
Orchestration): when a milestone is met, ping the relevant counterparty
(inspection cleared → trigger earnest-money deposit; title cleared; funded).

## Goals

1. Expose the orchestrator over gRPC so the brain genuinely routes/emits the
   counterparty ping (mirrors how `Closer.GenerateContract` made the Python
   Closer reachable).
2. Let a broker advance a signed deal through the four milestones and see each
   counterparty "pinged", on the broker dashboard.
3. Auto-record `inspection_cleared` when a broker completes a linked inspection.
4. Show the buyer a read-only closing progress tracker on their contract.

## Invariants preserved

- **No external paid calls.** `RecordMilestone` is an internal brain gRPC call on
  a *broker action* (exactly like `GenerateContract` on sign) — never RentCast /
  Anthropic, never on a page render.
- **Honest simulation.** The counterparty ping to escrow/title/lender is
  **simulated, recorded, and audited**, labeled as such; the real integration
  stays a documented seam (consistent with the SMS/Email simulated transport).
- **Append-only audit.** Every recorded milestone writes one `AuditEvent`.
- **Rails owns business state; the brain is stateless compute.** Rails enforces
  idempotency and ordering; the brain RPC is a pure routing/ping function.

## Design

### A. Brain — expose the orchestrator via `Closer.RecordMilestone`

Extend the existing `Closer` service (no new servicer; `CloserServicer` already
registered in `server.py`):

```proto
service Closer {
  rpc GenerateContract(GenerateContractRequest) returns (GenerateContractResponse);
  rpc RecordMilestone(RecordMilestoneRequest) returns (RecordMilestoneResponse);
}
message RecordMilestoneRequest  { string deal_id = 1; string milestone = 2; }
message RecordMilestoneResponse { bool pinged = 1; string counterparty = 2; string message = 3; }
```

`CloserServicer.RecordMilestone`:
- Map `request.milestone` → `Milestone` enum; on failure `context.abort(INVALID_ARGUMENT)`.
- Build a `ClosingOrchestrator(deal_id=request.deal_id, sink=_CapturingSink())`,
  call `record(milestone, met=True)`.
- Return `pinged`, `counterparty` (the `Counterparty` value string), and a
  human `message` from a small milestone→action template
  (e.g. `"Notified escrow: earnest-money deposit triggered for {deal_id}"`).
- Stateless per call — no cross-call dedup (Rails guarantees one call per
  newly-met milestone).

`_CapturingSink` is a tiny `CounterpartySink` that stores the single emitted
`CounterpartyPing` for the response (in `server.py`, not a change to `closing.py`).

### B. Rails state — the deal is the signed Offer

New model `ClosingMilestone` (`app/models/closing_milestone.rb`):
- `belongs_to :offer`
- columns: `milestone` (string), `counterparty` (string), `ping_message`
  (string), `ping_status` (`simulated` | `pending`), `recorded_at` (datetime)
- `MILESTONES = %w[inspection_cleared earnest_deposited title_cleared funded]`
- validations: `milestone` ∈ MILESTONES, `ping_status` ∈ `%w[simulated pending]`
- **unique index `[offer_id, milestone]`** — DB-level idempotency.

`Offer` additions:
- `has_many :closing_milestones, dependent: :destroy`
- `MILESTONE_ORDER = ClosingMilestone::MILESTONES`
- `deal_id` → `"deal-#{id}"`
- `recorded_milestones` → set of recorded milestone names
- `next_closing_milestone` → first of `MILESTONE_ORDER` not yet recorded (nil if done)
- `closing_complete?` → all four recorded

### C. Rails coordinator + gRPC client

`ClosingClient` (`app/services/closing_client.rb`) mirrors `CloserClient`:
- `initialize(stub: nil, addr: nil)`, `addr` defaults to `ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")`
- `record_milestone(deal_id:, milestone:)` → `Result(pinged, counterparty, message, error)`,
  using `Realestate::V1::Closer::Stub`; rescue `StandardError` → `Result(error: "closing_unavailable")`.

`ClosingOrchestration` (`app/services/closing_orchestration.rb`) —
`Result(milestone, counterparty, ping_message, ping_status, recorded, reason)`:
- `self.record(offer:, milestone:, client: ClosingClient.new)`
- **Idempotent:** if a `ClosingMilestone` for `[offer, milestone]` exists →
  `Result(recorded: false, reason: "already recorded")`, no ping.
- **Order-enforced:** if `milestone != offer.next_closing_milestone` →
  `Result(recorded: false, reason: "complete <prev> first")`, no record.
- Call `client.record_milestone(deal_id: offer.deal_id, milestone:)`.
  - ok → `counterparty`/`message` from the brain, `ping_status: "simulated"`.
  - error → fall back to `RAILS_ROUTING` (a small local copy of the
    milestone→counterparty map) + a templated message, `ping_status: "pending"`.
- Create the `ClosingMilestone` (`recorded_at: Time.current`).
- `AuditEvent.record_rail_trip(kind: "milestone_recorded", decision: milestone,
  subject: offer, detail: "<counterparty> pinged (<ping_status>): <message>")`.
- Return `Result(recorded: true, ...)`.

`RAILS_ROUTING = { "inspection_cleared" => "escrow", "earnest_deposited" =>
"escrow", "title_cleared" => "title", "funded" => "lender" }` — fallback only;
the brain is the source of truth on the happy path.

### D. Broker dashboard closing panel

`Broker::DashboardController#show` adds
`@closing_deals = Offer.where(status: "signed").includes(:closing_milestones, :property, :lead)`.

A new partial renders, per signed deal, the four-step tracker: each met step
shows ✓ + counterparty + ping_status + `recorded_at`; the `next_closing_milestone`
shows a `button_to` to `Broker::ClosingsController#create`. `closing_complete?`
deals show **"✅ Closed — funded."**

Route: under `namespace :broker`, on `resources :offers` add
`post :closing, on: :member` → `Broker::ClosingsController#create` reads
`params[:milestone]`, calls `ClosingOrchestration.record(offer:, milestone:)`,
redirects to the dashboard with the result (notice on `recorded`, alert on the
ordering/idempotency `reason`). `Broker::ClosingsController < Broker::BaseController`
(broker allowlist applies).

### E. Inspection auto-link

Migration: add nullable `offer_id` to `appointments` (+ index); `Appointment
belongs_to :offer, optional: true`.

When a broker marks an **inspection** appointment `completed`
(`Broker::AppointmentsController` — add a `complete` member action, or extend the
existing confirm/decline set with `complete`), resolve its deal:
- explicit `appointment.offer`, else
- auto-match: a single signed `Offer` for `appointment.property` whose
  `lead.contact` matches `appointment.requester_email` (or the sole signed offer
  on that property).
If resolved, call `ClosingOrchestration.record(offer:, milestone: "inspection_cleared")`
(same coordinator → same idempotency/order/audit). No resolution → just mark the
appointment completed (no closing effect). The manual dashboard button remains
the universal path.

### F. Buyer-visible read-only tracker

`consumer/contracts#show` renders a shared `_closing_tracker` partial from
`@contract.offer.closing_milestones` — **read-only**, no buttons. Honest footer:
"escrow / title / lender notifications are simulated in this demo." The same
partial backs the broker panel's status display (DRY), with broker-only buttons
rendered by the broker view.

## Components & boundaries

- `closing.py` — unchanged (already correct + tested).
- `CloserServicer.RecordMilestone` + `_CapturingSink` — thin gRPC adapter over the
  orchestrator.
- `ClosingMilestone` — persisted state, one row per met milestone.
- `ClosingClient` — gRPC transport (mirrors `CloserClient`).
- `ClosingOrchestration` — the one place that records a milestone (idempotency,
  order, ping, audit); every entry point (broker button, inspection completion)
  goes through it.
- `Broker::ClosingsController` — thin; `_closing_tracker` partial — shared
  read-only view.

## Data flow

1. Broker signs an offer (existing) → `status: "signed"` → appears in
   `@closing_deals`.
2. Broker clicks "Inspection cleared" (or completes a linked inspection) →
   `ClosingOrchestration.record` → `ClosingClient` → brain `RecordMilestone`
   routes to **escrow** + message → `ClosingMilestone(simulated)` + `AuditEvent`.
3. Repeat for earnest → escrow, title → title, funded → lender; on `funded` the
   deal is `closing_complete?`.
4. Buyer opens their contract → read-only tracker reflects the same rows.

## Error handling

- Brain unreachable → milestone still recorded, `ping_status: "pending"`,
  counterparty from `RAILS_ROUTING`, audited; tracker shows "ping pending".
- Out-of-order milestone → no record, broker sees "complete <prev> first".
- Re-recording a met milestone → no-op (unique index + service guard), no second
  ping/audit.
- Invalid milestone string at the brain → `INVALID_ARGUMENT`; `ClosingClient`
  surfaces it as `error` → treated as brain-unreachable fallback (still honest).

## Testing

- **Brain** (`services/brain/tests/test_server.py` or a new
  `test_closer_servicer.py`): `RecordMilestone` valid → `pinged=True`,
  `counterparty` correct per milestone; invalid milestone → `INVALID_ARGUMENT`.
  (`test_closing.py` already covers the orchestrator.)
- **Rails:**
  - `ClosingMilestoneTest` — unique `[offer, milestone]`; enum validations.
  - `ClosingOrchestrationTest` — records + audits; idempotent no-op; order
    enforcement; brain-down fallback (`pending` + `RAILS_ROUTING`); a stubbed
    client asserts the deal_id/milestone passed.
  - `ClosingClientTest` — stubbed stub maps the response; rescue → error result.
  - `Broker::ClosingsControllerTest` — button records the next milestone, shows
    on the dashboard; out-of-order shows the alert.
  - `Broker::AppointmentsControllerTest` — completing a linked inspection
    auto-records `inspection_cleared`; unlinked inspection does not.
  - `Consumer::ContractsControllerTest` — the read-only tracker renders for the
    contract's party and shows no broker buttons.
- Targets: brain ~238 → +~3; Rails 289 → +~12. Go builds clean (proto regen).

## Out of scope

- Real escrow/title/lender integrations (the `GrpcCounterpartySink` /
  carrier-binding seam).
- Un-recording / reversing a milestone (`met: false`) — broker only advances.
- Neighborhood **news** signal (#1) and omnichannel shared thread (#4) — later
  clusters.

## Migration notes

Two migrations: `create_closing_milestones` and `add_offer_to_appointments`.
Local Postgres is not running; both are hand-mirrored into `db/schema.rb`
(version bump) as in prior pillars. Proto regen via
`make proto PYTHON=/opt/anaconda3/bin/python3` (plain `make proto` resolves
python3 to a grpc_tools-less interpreter). New gRPC stubs (Go/Python/Ruby)
committed.
