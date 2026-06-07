# Design — Dynamic Scheduling (PRD R6)

Date: 2026-06-06
Status: approved (roadmap step 2 of 6); this is its own spec per the agreed sequence.
Predecessor: `2026-06-06-brain-realtime-valuation-design.md` (R3, merged).

Scope of THIS spec: **R6 only** — autonomously book property tours / inspections,
avoiding conflicts. Currently 🔴 *zero code* (confirmed: no appointment / calendar /
availability / showing / tour concept anywhere in the repo).

---

## 1. Goal

Let a buyer (self-serve or via the agent sidebar) **request a showing** for a listing
and get **real, conflict-free time slots**; let a broker **confirm or decline** from the
existing dashboard queue. The "dynamic" part is a genuine **collision-avoidance
algorithm** — not a fake calendar integration — so two showings never double-book the
same property or the same broker, and unshowable properties are never offered.

Non-goal: integrating a real external calendar (Google/Outlook). That would be a fake
seam in a demo; this project's ethos is glass-box honesty. We model availability and
collisions for real, in our own DB, deterministically.

## 2. Honest-scheduling principle (the project invariant, applied)

Consistent with "no source → no claim" and "live site never calls RentCast":

- **Slots are computed, never fabricated.** Candidate slots come from a deterministic
  generator (business-hours window × horizon × slot length) **minus** real existing
  bookings **minus** real blackout rules. If nothing is free, we say so.
- **No external network calls.** Scheduling touches the DB only. (Trivially preserves
  the zero-RentCast invariant.)
- **Every state change is audited** via the existing append-only audit-event chain
  (same pattern as `EnqueueHandoff`).
- **Re-check at commit.** Availability shown ≠ availability guaranteed; the booking and
  the broker-confirm both **re-run collision detection at write time** and a DB-level
  guard prevents an overlapping double-book under a race.

## 3. The collision-avoidance algorithm (the real "dynamic" core)

`ShowingScheduler` (Rails domain service, pure DB, deterministic given an injected
reference time):

**Inputs:** subject `Property`, reference `now`, config (slot length, horizon days,
daily window, optional assigned broker).

**Candidate generation:** for each day in `[now, now + horizon)`, emit fixed-length
slots across the daily window (e.g. 09:00–18:00, 30-min slots).

**Subtractions (a slot is dropped if any holds):**
1. **In the past** relative to `now` (no booking yesterday).
2. **Property collision** — overlaps an existing `requested` or `confirmed` Appointment
   for this property.
3. **Broker collision** — overlaps another Appointment for the same assigned broker
   (a broker can't be in two places at once).
4. **Property not showable** — `Property.state` is `under_offer`/`sold`, or `retired_at`
   set ⇒ no slots at all (honest empty result + reason).

**Output:** an ordered list of free `[start, end]` slots (capped to a sane N for UI),
plus a `reason` when empty ("under offer", "no availability in the next N days").

Determinism: callers inject `now`; tests pass a fixed reference time. (No `Time.now`
buried in the algorithm — same discipline the workflow/runtime enforces elsewhere.)

## 4. Data model

New `Appointment` (a.k.a. showing) — one migration, hand-edited into `db/schema.rb`
for local SQLite tests (local Postgres not running), per existing project practice.

| Column | Type | Notes |
|---|---|---|
| `property_id` | ref, not null | the listing being shown |
| `lead_id` | ref, nullable | set when a known lead books; null for anonymous buyer self-serve |
| `kind` | string, not null | `tour` \| `inspection` |
| `status` | string, not null | `requested` → `confirmed` \| `declined` \| `cancelled` \| `completed` |
| `starts_at` / `ends_at` | datetime, not null | the slot |
| `requester_name` / `requester_email` | string | who asked (lightweight, like Visitor) |
| `broker_email` | string, nullable | assigned broker (for broker-level collision) |
| `notes` | text | optional |
| `confirmed_at` / `declined_at` | datetime | audit timestamps |
| timestamps | | |

Indexes: `[property_id, starts_at]`, `[status]`. Status/kind validated by inclusion.
Scopes: `active` (`requested`+`confirmed`), `pending` (`requested`, newest-or-soonest),
`upcoming`. Overlap helper for the collision queries.

**No external availability table for v1.** Broker availability = "business hours minus
what's already booked," which is the realistic default and keeps the surface tight. (A
broker-managed availability editor is a clean later extension; called out as out-of-scope.)

## 5. Flows

**Buyer self-serve (primary demo path):**
1. Listing page (`Buyer::ListingsController#show`) renders the next free slots from
   `ShowingScheduler` (real, collision-aware).
2. `POST /buyer/listings/:id/showings` with a chosen slot → re-check collision →
   create `Appointment(status: requested)` → enqueue to broker (audit event) →
   confirmation UI ("requested — pending broker confirmation").

**Agent-driven path (ties scheduling to the Brain):**
- The agent sidebar message flow (`Agent::MessagesController#create`) detects a
  **scheduling intent** and renders the same real available-slots partial inline, so a
  buyer chatting "can I tour this Friday?" gets actual bookable slots. Booking reuses
  the buyer POST path. (See §6 for where intent detection lives.)

**Broker confirm (existing dashboard):**
- `Broker::DashboardController#show` gains a `@pending_showings` queue
  (`Appointment.pending`).
- `POST /broker/appointments/:id/confirm` → re-check collision → `confirmed` + audit.
- `POST /broker/appointments/:id/decline` → `declined` + audit.

## 6. Brain involvement (minimal, honest, deterministic)

R6's intelligence is the **collision algorithm**, which lives in Rails (deterministic,
unit-testable) — *not* an LLM. To still make scheduling **agent-native**, the brain gets
a small, deterministic **scheduling-intent classifier** so the orchestrator/agent can
recognize "I want to tour / see / visit / book a showing" from neutral phrasing and
route to the slots UI.

- Lives as a pure function in the brain intake layer (keyword/neutral-signal based — **no
  LLM call, no new model cost**), mirroring the existing `buyer_intake` neutral-field
  discipline (Fair-Housing-safe: reads intent to tour, never protected attributes).
- Exposed so Rails can ask "is this message a scheduling request?" Two honest options;
  **chosen: a new lightweight gRPC `Scheduling.ClassifyIntent`** (keeps the
  Rails→brain boundary consistent and lets the classifier live with the other brain
  code) **OR**, if that proves heavy for the value, a deterministic Rails-side matcher
  with the same word list. Implementation plan will pick the lighter one that keeps a
  brain test; default to the Rails-side deterministic matcher to avoid proto churn, and
  add a brain-side unit-tested classifier function the plan can promote to gRPC later.

Decision recorded: **start with a deterministic classifier (unit-tested), no new gRPC
unless it earns its keep.** Booking itself never needs the brain.

## 7. proto / model / data changes

- **proto**: only if §6 promotes the classifier to gRPC. Default: **no proto change** in
  v1 (booking is pure Rails; classifier is deterministic). Keep the door open.
- **Rails**: new `Appointment` model + migration + `db/schema.rb` edit; new
  `ShowingScheduler` service; controller actions + routes (buyer `showings`, broker
  `appointments` confirm/decline); dashboard + listing-page view partials.
- **Brain**: a `scheduling` intent classifier function + tests (kept even if Rails owns
  the runtime matcher, so the capability is real and demonstrable).

## 8. UI surfacing (glass box)

- **Listing page**: "📅 Available showings" with the next real free slots and a
  request button; honest empty-state ("Under offer — not available for showings" / "No
  openings in the next N days").
- **Agent sidebar**: same slots inline when a tour intent is detected.
- **Broker dashboard**: a "Pending showings" queue alongside handoffs/offers, with
  Confirm / Decline, showing requester + property + requested slot.
- **Confirmation states** surfaced honestly (requested vs confirmed vs declined).

## 9. Testing strategy (hermetic, deterministic)

- `ShowingScheduler`: candidate generation; past-slot exclusion; property collision;
  broker collision; blackout (under_offer/sold/retired → empty + reason); injected
  reference time ⇒ deterministic.
- Booking: creates `requested`, re-checks collision, rejects an overlapping double-book
  (and a DB-guard race test), emits an audit event.
- Broker confirm/decline: status transitions + audit + collision re-check on confirm.
- Brain classifier: positive/negative phrasings; Fair-Housing-safe (no protected attrs).
- Existing brain + Rails suites stay green; SQLite, `bin/rails test`, serial.

## 10. Out of scope (R6)

Broker-managed custom availability windows/blackouts editor; real external calendar
sync; SMS/email reminders (that's R4, fixed last — a confirmed showing may *log* a
simulated notification consistent with the existing R4 seam, but no real send);
travel-time/geographic routing between back-to-back showings (lat/lng exist; a clean
later enhancement). Slot length / window / horizon are fixed config in v1.

## 11. Risks

- **Race double-book**: two buyers grab the same slot. Mitigation: commit-time re-check
  + a DB-level overlap guard (validation + targeted uniqueness on
  `[property_id, starts_at, status]` for active rows); test it.
- **Timezone**: keep everything in a single app timezone (America/Chicago / Austin) and
  store UTC; don't fake multi-tz. Document the assumption.
- **Determinism in tests**: never call `Time.now` inside the algorithm; inject `now`.
