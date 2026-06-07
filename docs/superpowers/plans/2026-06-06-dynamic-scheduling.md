# Implementation Plan — Dynamic Scheduling (R6)

Spec: `docs/superpowers/specs/2026-06-06-dynamic-scheduling-design.md`
Branch: `feat/brain-scheduling` (off merged `main` @ 7680822)
Method: TDD (red → green → refactor) per task; subagent-driven with spec + quality review gates.

Invariants (carry from R3): no external network calls (trivially zero RentCast); every
state change audited via `AuditEvent.record_rail_trip`; migrations hand-edited into
`db/schema.rb` (local Postgres not running → SQLite tests); `bin/rails test` runs under
rbenv Ruby 3.3.11 (`eval "$(rbenv init - zsh)"`, NOT system Ruby 2.6); algorithm is
**deterministic** — inject `now`, never call `Time.now` inside it.

Test counts to beat going in: **brain 206 / Rails 216** (both green). Keep them green;
add to them.

---

## Part A — Brain scheduling-intent classifier (Python, TDD)

Makes scheduling agent-native and real, with zero LLM cost. Pure, deterministic,
Fair-Housing-safe (reads tour intent, never protected attributes).

**Task A1 — `scheduling` intent classifier**
- File: `services/brain/src/brain/scheduling/__init__.py` (new package) with
  `classify_scheduling_intent(text: str) -> SchedulingIntent` returning a small frozen
  result `(wants_scheduling: bool, kind: "tour"|"inspection"|None, matched: tuple[str,...])`.
- Deterministic keyword/phrase matcher over neutral phrasing: tour / showing / see the
  house / visit / walk through / book a viewing / schedule (→ tour); inspection /
  inspect / inspector (→ inspection). Case-insensitive, word-boundary aware; ignores
  negation-free simple match for v1 (document the limitation).
- Tests (`services/brain/tests/test_scheduling_intent.py`):
  - positive: "Can I tour this house Friday?", "I'd like to schedule a showing",
    "set up an inspection" → wants_scheduling True, correct kind.
  - negative: "what's it worth?", "is this priced well?", "" → False, kind None.
  - Fair-Housing safety: a phrase mentioning a protected class but no tour intent →
    False (no leakage); a tour request that also contains a protected term still
    classifies on the *tour* signal only and the matched terms contain no protected attr.
  - exported in `brain` namespace if that's the package convention; otherwise importable
    from `brain.scheduling`.
- Keep it independent of the orchestrator graph (no graph wiring in v1 — Rails owns the
  runtime dispatch; this function is the real, tested capability the spec promises).

---

## Part B — Appointment model + collision-avoidance engine (Rails, TDD)

The real "dynamic" core.

**Task B1 — `Appointment` model + migration + schema.rb**
- Migration `db/migrate/20260606000002_create_appointments.rb` + hand-edit
  `db/schema.rb` (bump version to `2026_06_06_000002`).
- Columns per spec §4: `property_id` (not null, fk), `lead_id` (nullable, fk), `kind`,
  `status` (default "requested"), `starts_at`, `ends_at`, `requester_name`,
  `requester_email`, `broker_email`, `notes`, `confirmed_at`, `declined_at`, timestamps.
  Indexes `[property_id, starts_at]`, `[status]`.
- `app/models/appointment.rb`:
  - `KINDS = %w[tour inspection]`, `STATUSES = %w[requested confirmed declined cancelled completed]`.
  - `belongs_to :property`; `belongs_to :lead, optional: true`.
  - validations: kind/status inclusion; presence of starts_at/ends_at; `ends_at > starts_at`.
  - scopes: `active` (status in requested+confirmed), `pending` (requested), ordered by
    `starts_at`; `for_property(p)`; `for_broker(email)`.
  - `overlaps?(other_start, other_end)` helper (half-open intervals: overlap iff
    `starts_at < other_end && ends_at > other_start`).
- Tests (`test/models/appointment_test.rb`): validations, `ends_at > starts_at`, scopes,
  overlap helper boundaries (touching intervals do NOT overlap).

**Task B2 — `ShowingScheduler` service (collision core)**
- File: `app/services/showing_scheduler.rb`. Config constants: `SLOT_MINUTES = 30`,
  `HORIZON_DAYS = 7`, `DAY_START_HOUR = 9`, `DAY_END_HOUR = 18`, `MAX_SLOTS = 12`.
- `Result = Struct.new(:slots, :reason, keyword_init: true)` where `slots` is an array of
  `Struct(:starts_at, :ends_at)`; `reason` is nil when slots present, else a string.
- `self.available_slots(property:, now:, broker_email: nil, kind: "tour")`:
  1. blackout: `property.retired_at` present or `state` in `under_offer`/`sold` →
     `Result.new(slots: [], reason: "Not available for showings (#{property.state})")`.
  2. generate candidate slots over `[now, now+HORIZON_DAYS)` within the daily window.
  3. drop past slots (`start <= now`).
  4. drop property collisions (overlap any `Appointment.active.for_property`).
  5. drop broker collisions when `broker_email` given (overlap any `active.for_broker`).
  6. cap to `MAX_SLOTS`; empty → `reason: "No openings in the next #{HORIZON_DAYS} days"`.
- `self.slot_free?(property:, starts_at:, ends_at:, broker_email: nil)` — the commit-time
  re-check used by booking/confirm (true iff no active overlap on property or broker).
- Tests (`test/services/showing_scheduler_test.rb`), all with an injected fixed `now`:
  - generates business-hours slots within window; none before `now`.
  - a `confirmed` appointment removes the overlapping slot (property collision).
  - a broker's appointment on another property removes the slot for that broker.
  - `under_offer` / `sold` / `retired` property → empty + reason.
  - fully-booked horizon → empty + "No openings" reason.
  - `slot_free?` true/false around an existing active appointment.
  - determinism: same `now` → identical slot list.

---

## Part C — Buyer booking flow (TDD)

**Task C1 — request a showing**
- Route: under `namespace :buyer`, `resources :listings` gains
  `resources :showings, only: %i[create]` (→ `POST /buyer/listings/:listing_id/showings`).
- `app/controllers/buyer/showings_controller.rb#create`:
  - load `Property.browsable.find(listing_id)` (404 if not browsable).
  - parse chosen `starts_at` (+ derive `ends_at` from SLOT_MINUTES); `kind` param
    (default "tour"); requester name/email from the session visitor when present, else
    params (lightweight, like Visitor).
  - **re-check** `ShowingScheduler.slot_free?` → if not free, re-render with a "just
    taken, pick another" message (turbo_stream + html fallback like the agent controller).
  - create `Appointment(status: "requested")`; associate `lead` if the visitor maps to one.
  - `AuditEvent.record_rail_trip(kind: "showing_requested", decision: "queued",
    subject: appointment, detail: "...")`.
  - respond turbo_stream (a `_showing_confirmation` partial) + html redirect_back fallback.
- **Race guard**: add a model-level guard so two overlapping *active* rows for the same
  property can't both persist — a `validate` that re-queries active overlaps on create
  (DB-level partial unique index is awkward on SQLite; a validation + the commit re-check
  is the pragmatic guard — document it). Test the concurrent double-book is rejected at
  the second `create!`.
- Tests (`test/controllers/buyer/showings_controller_test.rb` + model guard test):
  successful request creates requested appointment + audit event; booking an unavailable
  (already-taken) slot is rejected; non-browsable listing → 404.

---

## Part D — Broker confirm / decline (TDD)

**Task D1 — broker actions + queue**
- Routes under `namespace :broker`: `resources :appointments, only: [] do member: post :confirm, post :decline end`.
- `app/controllers/broker/appointments_controller.rb`:
  - `confirm`: load appointment; **re-check** `ShowingScheduler.slot_free?` excluding
    itself; on success set `status: "confirmed"`, `confirmed_at: Time.current`, optional
    `broker_email` from the signed-in broker; audit (`kind: "showing_confirmed"`,
    `decision: "confirmed"`). On collision, decline-to-confirm with a flash + audit noting
    the conflict.
  - `decline`: set `status: "declined"`, `declined_at`; audit (`decision: "declined"`).
  - Guard both behind the existing broker auth (`Visitor#broker?` allowlist / however
    `Broker::DashboardController` gates — match it exactly).
- `Broker::DashboardController#show`: add `@pending_showings = Appointment.pending.includes(:property, :lead)`.
- Tests (`test/controllers/broker/appointments_controller_test.rb`): confirm transitions +
  audit; confirm on a now-conflicting slot is refused; decline transitions + audit;
  non-broker is rejected.

---

## Part E — Agent sidebar + UI surfacing (TDD where logic, view specs light)

**Task E1 — `ShowingIntent` (Rails runtime classifier) + agent dispatch**
- `app/services/showing_intent.rb`: `ShowingIntent.detect(query) -> result|nil` mirroring
  the brain classifier word list (the brain function is the canonical capability; this is
  the runtime matcher per spec §6). Returns kind ("tour"/"inspection") + matched, or nil.
- Wire into `Agent::MessagesController#create`: between `SearchIntent` and `price_check`,
  add `elsif (@showing = showing_for(@listing, @query))` → renders a `_showing` partial
  with real `ShowingScheduler.available_slots(property: @listing, now: Time.current)`.
  Only when a `@listing` is pinned (need a property to show). `view_for` returns
  `"showing"` accordingly.
- Tests (`test/controllers/agent/messages_controller_test.rb` additions +
  `test/services/showing_intent_test.rb`): a tour question on a listing renders slots; the
  same question with no listing falls through to the orchestrator; non-scheduling queries
  unaffected (regression).

**Task E2 — Views (glass box)**
- `app/views/buyer/listings/show.html.erb`: a "📅 Available showings" block from
  `ShowingScheduler` with a request form (POST to buyer showings); honest empty-state
  using `Result#reason`.
- `app/views/agent/messages/_showing.html.erb`: inline slots + request affordance.
- `app/views/buyer/showings/_showing_confirmation.html.erb`: "Requested — pending broker
  confirmation" state.
- `app/views/broker/dashboard/show.html.erb`: a "Pending showings" section with
  Confirm / Decline buttons.
- All new view branches `respond_to?`/presence-guarded so missing data degrades cleanly
  (match the R3 view discipline). Listing controller `#show` passes `@slots`.

---

## Part F — Docs + green suites

**Task F1 — docs + final verification**
- Update: `README.md` (capability matrix R6 → 🟢/real), `docs/ARCHITECTURE.md` (a
  scheduling section: model, collision algorithm, flows, honesty/no-external-calendar),
  `services/domain/README.md` (Appointment + ShowingScheduler + routes), and the PRD audit
  table in the R3 spec's predecessor note if appropriate (or note R6 done in this plan).
- Bump documented test counts to the new totals.
- Run full suites: brain (`pytest`) and Rails (`bin/rails test`) — both green, no skips.
- Confirm invariant: grep the new code for any RentCast/HTTP/network call → none.

---

## Execution order (subagent clusters)

1. **A1** (brain classifier) — isolated, no Rails dep.
2. **B1 → B2** (model+engine) — the core; must be solid before flows.
3. **C1** (buyer booking) depends on B.
4. **D1** (broker actions) depends on B.
5. **E1 → E2** (agent + views) depends on B, C.
6. **F1** (docs + whole-suite verification + final opus review).

Each cluster: fresh implementer (TDD) → spec-compliance review → code-quality review →
fix loop, then proceed. Final whole-feature review before finishing the branch.
