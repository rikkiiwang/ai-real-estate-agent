---
title: "feat: Omnichannel Concierge + intent triaging (engagement pillar)"
type: feat
status: active
date: 2026-06-05
origin: docs/brainstorms/2026-06-05-omnichannel-intent-triaging-requirements.md
---

# Omnichannel Concierge + Intent Triaging — implementation plan

## Summary

Make the spec's engagement-pillar capabilities **reachable** in the Rails
marketplace: a **unified cross-channel conversation thread** (Voice / SMS / Email /
Chat) and **buyer + seller intent triaging** (looky-loo vs high-intent), surfaced
through a new **Concierge console**, with high-intent contacts routed into the
**existing broker queue**. Transport is **simulated and labeled** — no carriers.

The existing `services/voice` Go primitives (channel-agnostic thread, neutral-
signals triage, per-channel AI disclosure) are the **design reference**; this plan
**re-implements them in Rails** so the thread is persisted, reachable from the
marketplace UI, and visible to the broker — rather than calling the undeployed,
in-memory Go service.

---

## Problem frame

Per the origin requirements, the engagement pillar exists in `services/voice` but
is unreachable, seller-only for triage, and has no Email channel or unified-thread
surface. The MVP gap is reachability + buyer triage + a demoable surface, not real
telephony (see origin: `docs/brainstorms/2026-06-05-omnichannel-intent-triaging-requirements.md`).

---

## Key technical decisions

- **KTD1 — Persist the thread in Rails (not call the Go service).** A `Conversation`
  has_many `Message` model owns the unified thread. Rationale: the Go session
  manager is in-memory and undeployed; the broker must *see* the thread; the demo
  must be reachable and test-backed. The Go code remains the design reference.
- **KTD2 — Triage is a Ruby service reading a fixed neutral allow-list.** Mirrors
  `services/voice/qualify.go` and `brain.lawyer.fair_housing` equal-service
  guarantee: buyer/seller signals only; protected-class/proxy inputs are
  structurally excluded (not in the allow-list), so they cannot change the outcome.
- **KTD3 — Reuse the existing broker queue.** High-intent ⇒ find/create a `Lead`
  (carries `intent`, `contact`, `address`) + a `HandoffPacket(trigger: "high_intent")`
  so it appears in `HandoffPacket.queue` on the broker dashboard. No new inbox.
- **KTD4 — Channels + disclosure are a small Ruby value layer.** Channel set
  `voice/sms/email/chat`; voice = mandatory AI disclosure, text = voluntary
  (ports `disclosure.go`). Adds `email`.
- **KTD5 — Simulated transport.** Messages are entered in the Concierge UI; an
  adapter boundary (`ChannelAdapter`) is the swappable seam, labeled
  "simulated transport — no live carrier." Real providers drop in later.

---

## High-level technical design

```
Concierge console (Rails view)                 Broker dashboard (existing)
  channel picker · composer · thread · badge      handoff queue ← high_intent
        │  POST /concierge/messages                         ▲
        ▼                                                   │
  ConciergeService.ingest(conversation, channel, body, signals)
        │  append Message(channel, role, body, ai_disclosed)
        │  merge neutral signals → Conversation.signals
        │  IntentTriage.call(signals, side) → label + reason + signals_used
        │  cache label on Conversation; if high_intent → Lead + HandoffPacket
        ▼
  Conversation (1) ──< Message (N, channel-tagged, ordered)
```

Switching the channel selector posts the next message on a new channel **to the
same `Conversation`**, so the thread and merged signals carry over unchanged (OC3).

---

## Implementation units

### U1. Conversation + Message persistence
- **Goal:** the unified, channel-tagged thread, persisted.
- **Requirements:** OC1, OC2, OC4 (origin).
- **Files:** `services/domain/app/models/conversation.rb`,
  `services/domain/app/models/message.rb`,
  `services/domain/db/migrate/*_create_conversations.rb`,
  `services/domain/db/migrate/*_create_messages.rb`,
  `services/domain/db/schema.rb`,
  `services/domain/test/models/conversation_test.rb`,
  `services/domain/test/models/message_test.rb`.
- **Approach:** `Conversation`(contact, name, side[buyer/seller], `signals` JSON,
  `intent` cached default "low_intent_browser") `has_many :messages`. `Message`
  (conversation, channel, role[visitor/agent], body, ai_disclosed:boolean,
  timestamps), default order by created_at. `Conversation#merge_signals(hash)`
  merges non-blank neutral keys.
- **Patterns to follow:** `Property`/`MarketSnapshot` model + migration style;
  JSON column like `Property.photo_urls`.
- **Test scenarios:** messages return in insertion order across channels; a
  voice then email message belong to one conversation; `merge_signals` keeps
  existing values and adds new non-blank ones; blank values ignored.

### U2. IntentTriage service (buyer + seller, neutral-only)
- **Goal:** label looky-loo vs high-intent from neutral signals only.
- **Requirements:** IT1, IT2, IT3, IT4, IT5 (origin).
- **Dependencies:** U1.
- **Files:** `services/domain/app/services/intent_triage.rb`,
  `services/domain/test/services/intent_triage_test.rb`.
- **Approach:** `NEUTRAL_SIGNALS = { buyer: %w[preapproval move_timeline_days budget], seller: %w[address timeline motivation] }`.
  Buyer high-intent = `preapproval` truthy AND `move_timeline_days` present and
  `<= 30`. Seller high-intent = address + (timeline or motivation) (ports
  `qualify.go`). Returns `Result(intent, high_intent, reason, signals_used)`.
  Reads ONLY allow-list keys from the signals hash — any other key (e.g. a
  protected attribute) is never consulted.
- **Patterns to follow:** `PriceCheck` / `NegotiationResponse` service-object
  shape (`Result = Struct`, `.call`).
- **Test scenarios:** buyer with preapproval + 20-day move ⇒ high_intent;
  preapproval but 90-day move ⇒ looky-loo; move ≤30 but no preapproval ⇒
  looky-loo; seller address+timeline ⇒ high_intent; seller address only ⇒
  looky-loo; **a protected-class key in the signals hash does not change the
  label** (equal service); `signals_used` lists only allow-list keys present;
  `reason` names the missing signal for looky-loo.

### U3. Channel + AI-disclosure value layer
- **Goal:** channel set + per-channel disclosure rules.
- **Requirements:** OC2, OC5 (origin).
- **Dependencies:** none.
- **Files:** `services/domain/app/services/channel.rb` (or module with
  `CHANNELS`, `mandatory_disclosure?`, `disclosure_text`),
  `services/domain/test/services/channel_test.rb`.
- **Approach:** channels `%w[voice sms email chat]`; `mandatory_disclosure?` true
  only for `voice`; `disclosure_text(channel)` returns voice copy for voice, the
  voluntary text otherwise (ports `disclosure.go`, adds email as a text channel).
- **Test scenarios:** voice ⇒ mandatory true + AI-disclosure copy; sms/email/chat
  ⇒ mandatory false; unknown channel rejected/validation; email treated as text.

### U4. ConciergeService — ingest, re-triage, route high-intent
- **Goal:** one entry point that appends a message, re-triages, and routes.
- **Requirements:** OC3, IT5, IT6, S4 (origin); KTD3.
- **Dependencies:** U1, U2, U3.
- **Files:** `services/domain/app/services/concierge_service.rb`,
  `services/domain/test/services/concierge_service_test.rb`.
- **Approach:** `ingest(conversation:, channel:, body:, signals:)` →
  validate channel, set `ai_disclosed` from disclosure rules, append `Message`,
  `merge_signals`, recompute `IntentTriage`, cache `intent` on conversation; if it
  newly becomes high-intent, find_or_create a `Lead`(contact, address from
  signals, side, intent) and a `HandoffPacket(trigger: "high_intent", reason,
  recommended_action: "Engage high-intent <side> — pre-approved / near-term")` —
  **once** (idempotent: don't double-enqueue on subsequent high-intent messages).
- **Patterns to follow:** how `NegotiationResponse` / the seller flow create
  `EnqueueHandoff`/`HandoffPacket`; `Lead` creation in existing offer flow.
- **Test scenarios:** appending on a 2nd channel preserves prior turns + signals
  (OC3); becoming high-intent creates exactly one HandoffPacket in
  `HandoffPacket.queue`; staying looky-loo creates none; a further high-intent
  message does NOT create a second packet; voice message records ai_disclosed=true.

### U5. Concierge console (controller + views + Stimulus)
- **Goal:** the reachable demo surface.
- **Requirements:** S1, S2, S3, S4, OC4, OC6 (origin).
- **Dependencies:** U4.
- **Files:** `services/domain/app/controllers/concierge_controller.rb`,
  `services/domain/app/views/concierge/show.html.erb`,
  `services/domain/app/views/concierge/_thread.html.erb`,
  `services/domain/app/views/concierge/_message.html.erb`,
  `services/domain/app/javascript/controllers/concierge_controller.js` (channel
  select), `services/domain/config/routes.rb`,
  `services/domain/test/controllers/concierge_controller_test.rb`.
- **Approach:** `GET /concierge` shows a conversation (create/find one for the
  session/visitor or a demo contact); a channel `<select>` (voice/sms/email/chat),
  a body field, and quick "signal" toggles (pre-approved, move-in ≤30 days) to make
  triage demoable; `POST /concierge/messages` calls `ConciergeService.ingest` and
  re-renders the thread + intent badge via a Turbo frame. Thread shows each
  message's channel + AI-disclosure note; a "simulated transport" label (OC6); a
  "routed to broker" notice when high-intent (S4).
- **Patterns to follow:** the agent sidebar's Turbo-frame post/re-render; the
  seller flow's `turbo_frame_tag` result pattern; existing Stimulus controllers
  (`listing_filter_controller.js`).
- **Test scenarios:** GET renders the thread + intent badge; posting a message
  appends it and re-renders; switching channel and posting keeps the same thread
  (S2); toggling pre-approved + ≤30-day move flips the badge to high-intent (S3)
  and shows the routed-to-broker notice (S4); voice channel shows the mandatory
  AI-disclosure note.

### U6. Broker visibility of the cross-channel thread
- **Goal:** broker sees high-intent concierge leads + their thread.
- **Requirements:** IT6, S4 (origin).
- **Dependencies:** U4, U5.
- **Files:** `services/domain/app/controllers/broker/dashboard_controller.rb`
  (extend), `services/domain/app/views/broker/dashboard/show.html.erb` (extend),
  `services/domain/test/controllers/broker/dashboard_controller_test.rb` (extend).
- **Approach:** the `high_intent` HandoffPacket already lands in the queue (U4);
  link/show its `Conversation` thread (channels + signals used) from the broker
  dashboard so the broker sees how the lead qualified. Keep it read-only.
- **Test scenarios:** a high-intent conversation's packet appears in the broker
  queue with trigger `high_intent`; the broker view shows its channels + the
  neutral signals that triggered triage; a non-broker visitor still cannot reach it.

### U7. Wiring: nav, demo seed, README coverage matrix
- **Goal:** reachable from nav, seeded for the demo, docs aligned.
- **Requirements:** success criteria (origin); README accuracy.
- **Dependencies:** U5.
- **Files:** `services/domain/app/views/layouts/marketplace.html.erb` (nav link),
  `services/domain/db/seeds.rb` (a demo conversation spanning ≥3 channels),
  `README.md` (Voice rows → R5 ✅ buyer+seller, R6 ✅ reachable omnichannel thread),
  `docs/ARCHITECTURE.md` (note the Concierge surface),
  `services/domain/test/...` (nav/seed smoke as fits).
- **Approach:** add a "Concierge" nav link; seed one demo conversation
  (Chat → SMS → Voice → Email, ending high-intent) so the demo and broker queue
  have content; update the README coverage matrix rows reworded earlier (R5 now
  buyer+seller reachable; R6 now ✅ reachable, voice/SMS/email simulated).
- **Test scenarios:** nav link present on a marketplace page; `db:seed` is
  idempotent and yields a multi-channel demo conversation; `ListingSearch`/other
  suites unaffected.

---

## Scope boundaries

### Deferred for later (by design)
- Real carriers (Twilio voice/SMS, email gateway), phone numbers, inbound webhooks;
  low-latency live voice (STT/turn-taking). Transport stays simulated + labeled.
- Trained intent model — thresholds are demo-tuned heuristics.

### Outside this feature
- The existing buyer/seller journeys and the Ask-Atlas sidebar are untouched.
- Tour/inspection scheduling (R7) — separate gap, not in scope here.

### Deferred to follow-up work
- Porting the Rails triage back into the Go `qualify.go` for parity, or exposing
  the Concierge over the gateway REST API.

---

## Requirements traceability
- OC1/OC2/OC4 → U1; OC3 → U4/U5; OC5 → U3/U5; OC6 → U5.
- IT1–IT5 → U2; IT6 → U4/U6.
- S1–S4 → U5; broker visibility → U6; reachability/docs → U7.

---

## Test strategy
- Models + services unit-tested (U1–U4); controller/integration tests for the
  console and broker visibility (U5–U6). The Fair-Housing/equal-service test in U2
  is the key safety lock (protected-class input cannot change triage). Full Rails
  suite must stay green; update the documented test count after landing.
- No external network; simulated transport keeps everything hermetic.

---

## Risks
- **Scope vs. submission time.** Mitigation: 7 small units, Rails-only, reuse the
  broker queue; UI is a single console with Turbo re-render.
- **Equal-service regression.** Mitigation: explicit allow-list + a test proving a
  protected-class key is inert.
- **Demo emptiness.** Mitigation: U7 seeds a multi-channel high-intent conversation.
