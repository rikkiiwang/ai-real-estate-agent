---
title: "feat: Omnichannel engagement + intent triaging (Concierge)"
type: feat
status: active
date: 2026-06-05
origin: brainstorm (ce-brainstorm)
---

# Omnichannel Interaction + Intent Triaging — requirements

## Problem & context

The spec's **Voice pillar** (engagement & qualification) asks for two capabilities
that exist in code but are **not reachable** from the product:

1. **Omnichannel Interaction** — a consumer can move between **Voice, SMS, Email,
   and Chat** without losing the conversation **thread** (context carries over).
2. **Intent Triaging** — distinguish a **looky-loo** (browsing) from a
   **high-intent buyer** (pre-approved for financing, needs to move in ~30 days),
   so the human broker's attention goes to ready parties.

What already exists (in `services/voice`, Go):
- `session.go` — a **channel-agnostic thread/session backbone**: sessions keyed by
  id hold an ordered list of turns; "any channel can append to the same thread."
- `disclosure.go` — channel types `voice` / `chat` / `sms` with per-channel
  **AI-disclosure** rules (voice = mandatory 30s gate; text = voluntary). **No
  email channel.**
- `qualify.go` — **seller-side** triage (high-intent = address + timeline/
  motivation), neutral-signals-only (Fair-Housing equal-service guarantee).

Gaps: none of it is reachable from the marketplace; there is **no buyer-side
triage**; **no Email channel**; and no surface that demonstrates a unified
cross-channel thread.

## Goal

Make both capabilities **reachable and demonstrable** through a new **Concierge
console** in the marketplace, backed by the existing engagement backbone, using
**demo-grade simulated transport** (no external telephony/SMS/email providers).

## Users & value

- **Consumer (buyer/seller):** one continuous conversation that follows them
  across channels — no repeating themselves when they switch from email to a call.
- **Broker (HITL):** ready, **high-intent** leads surface automatically into the
  existing review queue, with the full cross-channel thread and the neutral
  signals behind the triage.
- **Reviewer:** sees the engagement pillar's R5/R6 met and reachable, not just
  "logic exists in a service."

## Requirements

### Omnichannel Interaction
- **OC1.** A conversation is a **single thread per contact**; messages from any
  channel append to that one thread in order.
- **OC2.** Channels supported: **Voice, SMS, Email, Chat.** (Email is new.)
- **OC3.** Switching channels mid-conversation **preserves full context** — the
  thread and any collected neutral fields carry over unchanged.
- **OC4.** Each message records the **channel** it arrived on, shown in the thread.
- **OC5.** **Per-channel AI disclosure** is enforced/surfaced: voice = mandatory
  disclosure before a substantive turn; text channels = voluntary disclosure.
- **OC6.** Transport is **simulated and clearly labeled** ("simulated transport —
  no live carrier"); the channel adapter is a swappable seam so a real provider
  can drop in later without changing the thread model.

### Intent Triaging
- **IT1.** Triage labels a contact as **looky-loo** (low-intent) or **high-intent**.
- **IT2.** **Buyer** high-intent requires neutral transaction signals:
  **financing pre-approval** AND a **near-term move (≤ ~30 days)**. Anything short
  stays looky-loo; missing data is never invented.
- **IT3.** **Seller** triage is retained (address + timeline/motivation) and the
  two are unified under one engagement-intent concept.
- **IT4.** Triage reads **only neutral, transaction-relevant signals** — never a
  protected class or proxy (mirrors the Fair-Housing equal-service guarantee). The
  allow-list is explicit and structurally enforced.
- **IT5.** The label is **live**: it flips looky-loo → high-intent as qualifying
  signals accumulate in the thread, and explains **which signals** drove it.
- **IT6.** A contact that becomes **high-intent flows into the existing broker
  handoff queue** with its cross-channel thread and the signals used.

### Surface (Concierge console)
- **S1.** A reachable marketplace page where you choose a channel, send a message,
  and watch it land in **one unified thread**.
- **S2.** Switching the channel selector mid-conversation shows the **same thread**
  continuing (demonstrates OC3).
- **S3.** A visible **intent badge** that updates as signals are added, with the
  reason/signals shown.
- **S4.** When a contact reaches high-intent, a clear affordance/notice that it has
  been **routed to the broker queue** (and it appears there).

## Success criteria
- One thread carried across **≥3 channels** (e.g., Chat → SMS → Voice → Email)
  with context intact — demonstrable end-to-end.
- Intent flips to high-intent **only** when pre-approval + ≤30-day move are present
  (buyer) or address + timeline/motivation (seller); stays looky-loo otherwise.
- A high-intent contact appears in the **broker queue** with its thread + signals.
- Triage is proven (test) to read **only neutral signals** — protected-class inputs
  cannot change the outcome.
- Per-channel AI disclosure enforced (voice mandatory) — tested.
- Tests green (Go + Rails + any brain), **deployed**, reachable in the live demo;
  README coverage matrix updated (R5 ✅ buyer+seller, R6 ✅ reachable omnichannel).

## Scope boundaries

### Deferred for later (by design)
- **Real carriers/providers** — Twilio voice/SMS, a real email gateway, phone
  numbers, inbound webhooks. Transport is simulated and labeled; the adapter seam
  is real.
- **Low-latency live voice** (speech-to-text/turn-taking) — out of MVP scope per
  the spec ("MVP is single-channel"); the Concierge proves the thread/disclosure
  model that a real voice transport would plug into.
- Intent thresholds are **demo-tuned heuristics**, not a trained model.

### Outside this feature
- Changing the existing buyer/seller marketplace journeys or the agent sidebar.
- Real scheduling/calendar booking (R7) — separate gap, not in this feature.

## Dependencies / assumptions
- Reuses the `services/voice` thread/disclosure/qualify primitives; the unified
  thread must be reachable from the Rails marketplace and visible to the broker —
  **persistence vs. live-service call is a planning decision** (the brainstorm
  does not fix the storage shape).
- The broker queue already exists (`EnqueueHandoff` / the broker dashboard); IT6
  routes into it rather than building a new inbox.
- Fair-Housing equal-service guarantee already exists on both the brain and voice
  sides; buyer triage extends the same neutral-allow-list pattern.

## Open questions (for planning)
- Where the unified thread lives so both the Concierge UI and the broker see it
  (Rails-persisted conversation vs. calling the Go voice service).
- Exact neutral buyer-signal keys (e.g., `preapproval`, `move_timeline`) and the
  ≤30-day threshold representation.
