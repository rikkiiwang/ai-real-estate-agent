# Omnichannel (R4) — Design

Date: 2026-06-08
Status: Implemented
Cluster: 3 (R4 omnichannel — the last brain-completeness pillar). Decided: **Full**
scope incl. voice; **shared-secret** webhook auth (signature validation a
documented seam); **record every sidebar turn** (full text for chat/orchestrate,
a short summary for card answers).

## Problem

Functional requirement #2 ("Voice"): the agent must move between **Voice, SMS,
Email, and Chat without losing the thread**. Today the channel *seam* is clean —
`ChannelTransport.deliver` routes to `TwilioSms`/`SendgridEmail` (both currently
`raise NotImplementedError`) or a working `Simulated` fallback, gated by ENV — but
there is **no shared thread**: `thread_id` is a session-cookie UUID handed to the
brain's in-process LangGraph memory; nothing is persisted in Rails. The
`Conversation`/`Message` models existed but were dropped. There are no inbound
webhooks. The Go voice service is standalone (own in-memory thread, not even
wired to the brain). `HandoffPacket.transcript` is never populated, so the broker
dashboard's "Cross-channel thread" (which already renders the field when present)
is always empty.

## Goals

1. One **persisted Conversation thread** every channel reads/writes, so the agent
   keeps context when a lead switches channels.
2. **Real Twilio/SendGrid adapters** (outbound + inbound) behind the ENV gate.
3. The broker sees the **unified cross-channel transcript** on handoff.
4. The **voice** service participates in the same thread.

## Invariants preserved

- **Zero external calls in the demo.** SMS/Email stay on the `Simulated`
  transport unless Twilio/SendGrid keys are set; real adapters fire only on an
  explicit send/inbound when configured, never on a page render.
- **AI disclosure** is recorded per message; voice mandates disclosure.
- **Neutral-signals-only triage** (R5) unchanged.
- **No proto change**: the brain already keys LangGraph memory by `thread_id`; we
  point that at the durable conversation. The Rails `Conversation` is the durable
  cross-channel record; the brain's in-process memory carries context while warm.

## Design

### A. The shared thread (persistence core)

`Conversation` (`app/models/conversation.rb`):
- columns: `contact` (string, unique — normalized email or E.164 phone), `name`,
  `last_channel`, timestamps.
- `Conversation.for(contact:, name: nil)` — find-or-create by normalized contact.
- `#thread_id` → `"conv-#{id}"` (the brain handle).
- `#append(channel:, role:, body:, ai_disclosed: false)` → creates a `Message`,
  updates `last_channel`; returns the message.
- normalizes `contact` (downcase email; strip non-digits for phone — a value
  containing `@` is treated as email, else phone).

`Message` (`app/models/message.rb`):
- `belongs_to :conversation`; columns `channel`, `role`, `body`, `ai_disclosed`,
  timestamps. `CHANNELS = Channel::CHANNELS`; `ROLES = %w[user agent broker]`.
- default scope order by `:created_at`.

**Boundary:** persistence requires an identity (a `contact`). Signed-in visitors
and inbound senders get a durable thread; anonymous sidebar use keeps today's
ephemeral session behaviour.

### B. Agent sidebar joins the thread

`Agent::MessagesController#create`:
- `@conversation = current_visitor && Conversation.for(contact: current_visitor.email, name: current_visitor.name)`.
- `thread_id` becomes `@conversation&.thread_id || (session[:agent_thread_id] ||= SecureRandom.uuid)`.
- Append the **user** turn before answering: `@conversation&.append(channel: @channel,
  role: "user", body: @query, ai_disclosed: Channel.mandatory_disclosure?(@channel))`.
- After the answer, append the **agent** turn with a body from `AgentReplySummary`
  (full text for chat/orchestrate `@result.message`; a one-line summary for
  card answers — e.g. "Shared a price check for <address>", "Answered: how's this
  neighborhood?"). Records every turn so the thread is complete.

Sidebar view (`shared/_agent_sidebar.html.erb`): when `signed_in?`, render the
visitor's `Conversation` history (each bubble tagged with its `channel`) in
`#agent-messages` instead of only the static greeting — so switching the channel
selector visibly preserves the thread. `Visitor#conversation` → `Conversation.find_by`
normalized email.

### C. Real provider adapters (behind the ENV gate)

In `channel_transport.rb`, replace the two `raise`s:
- `TwilioSms#deliver(to:, body:)` → `Net::HTTP` POST to
  `https://api.twilio.com/2010-04-01/Accounts/#{SID}/Messages.json` with basic
  auth (`SID`/`AUTH_TOKEN`), form body `From=TWILIO_FROM,To=to,Body=body`. Returns
  `Result(status: "sent", provider: "twilio", note: sid)`. Rescue → `Result(status:
  "error", provider: "twilio", note: msg)`.
- `SendgridEmail#deliver(to:, body:)` → `Net::HTTP` POST to
  `https://api.sendgrid.com/v3/mail/send` with `Authorization: Bearer SENDGRID_API_KEY`,
  JSON `{personalizations:[{to:[{email:to}]}], from:{email: SENDGRID_FROM},
  subject:"Atlas", content:[{type:"text/plain", value: body}]}`. Returns
  `Result(status:"sent", provider:"sendgrid")`; rescue → error Result.
- `configured?` and the `Simulated` fallback are unchanged, so the demo (no keys)
  stays simulated. **No HTTP is constructed unless `configured?` is true.**

### D. Inbound webhooks (real two-way)

`Inbound::BaseController < ActionController::Base` — `skip_forgery_protection`;
`before_action :verify_webhook_token` (compares `params[:token]` or an
`X-Webhook-Token` header to `ENV["INBOUND_WEBHOOK_TOKEN"]`; 401 on mismatch; if the
ENV is unset, 401 — inbound is off until configured). Full Twilio-signature /
SendGrid validation is the documented production seam.

A shared `InboundTurn` service: `InboundTurn.call(contact:, name:, channel:, body:)`
→ find/create `Conversation`, append user turn, run
`BrainConversationClient.orchestrate(query: body, thread_id: conversation.thread_id)`,
append the agent turn, return the reply text (brain-down → a friendly fallback
string, still appended).

- `Inbound::SmsController#create` (Twilio): reads `From`/`Body`; `InboundTurn`
  with `channel: "sms"`; responds **TwiML** `<Response><Message>#{reply}</Message></Response>`
  (Twilio relays it as the SMS reply — no outbound call).
- `Inbound::EmailController#create` (SendGrid Inbound Parse): reads `from`/`text`;
  `InboundTurn` with `channel: "email"`; sends the reply via
  `ChannelTransport.deliver(channel: "email", to: sender, body: reply)`; 200.

Routes: `namespace :inbound { post "sms"; post "email"; post "voice" }`.

### E. Broker cross-channel transcript

When a lead is handed off, populate `HandoffPacket.transcript` from the
`Conversation`. `Conversation#transcript` → messages formatted
`"[<channel>] <role>: <body>"`, newline-joined. Wire it where handoffs are
created from an identified contact:
- `Visitor#route_to_broker` (R5 engagement handoff) passes
  `transcript: conversation&.transcript` to `EnqueueHandoff`.
- `EnqueueHandoff.call` already accepts `transcript:`; the dashboard already
  renders it under a "Cross-channel thread" `<details>`. Net change: populate it.

### F. Voice into the shared thread

- Browser voice (the existing sidebar mic → `channel: "voice"`) already flows
  through B, so browser-voice turns persist in the thread for free.
- For the **standalone Go voice service**: `Inbound::VoiceController#create`
  (`contact`, `text` → `InboundTurn` channel `"voice"`, JSON `{reply:}`), guarded
  by the same token. Wire `services/voice` to POST each seller turn to
  `<DOMAIN_URL>/inbound/voice` and speak the returned `reply`, so the standalone
  service is a real thread participant. (Voice is not in the live demo unless
  `are-voice` is deployed with `DOMAIN_URL` + `INBOUND_WEBHOOK_TOKEN` set — an
  honest seam.)

## Components & boundaries

- `Conversation` / `Message` — the durable thread; one responsibility each.
- `InboundTurn` — the single inbound pipeline (append → orchestrate → append),
  shared by SMS/email/voice so behaviour is uniform.
- `AgentReplySummary` — maps a sidebar answer to a thread line (pure function).
- `Inbound::*Controllers` — thin provider adapters (parse → `InboundTurn` →
  provider-shaped reply).
- `TwilioSms` / `SendgridEmail` — outbound transport only (unchanged seam).

## Data flow

1. Signed-in visitor asks in **chat** → user+agent turns saved to their
   `Conversation`; brain keyed to `conv-#{id}`.
2. They switch the selector to **SMS** and ask a follow-up → same conversation,
   brain still has context (same `thread_id`); reply "delivered" simulated, saved
   tagged `sms`. Sidebar shows the interleaved thread.
3. A real inbound **email** from the same address (keys set) → `InboundTurn`
   appends to the same conversation → orchestrate → reply emailed.
4. Lead handed off → broker sees the full cross-channel transcript.

## Error handling

- Brain unreachable in `InboundTurn` → append a friendly fallback agent line,
  still reply (never a dead webhook).
- Missing/!match webhook token → 401.
- Outbound adapter error (configured but provider fails) → error `Result`; the
  sidebar shows the honest delivery note; nothing raises into the request.
- Unknown inbound sender → a new `Conversation` (no auth needed to start one).

## Testing

- `ConversationTest` / `MessageTest` — find-or-create by normalized contact;
  `append` + `transcript`; ordering; phone vs email normalization.
- `Agent::MessagesControllerTest` — a signed-in turn persists user+agent messages
  and reuses the conversation `thread_id`; the sidebar renders prior history;
  anonymous stays ephemeral (no `Conversation` rows).
- `ChannelTransportTest` — with stubbed `Net::HTTP`, `TwilioSms`/`SendgridEmail`
  build the right request **only when configured**; unconfigured still returns
  `Simulated` and makes no HTTP.
- `Inbound::SmsControllerTest` / `EmailControllerTest` / `VoiceControllerTest` —
  a simulated provider POST (with token) appends to the thread, orchestrates
  (stubbed brain), and returns TwiML / sends email / returns JSON; bad token → 401.
- `InboundTurnTest` — brain-down fallback still appends + replies.
- Handoff transcript — `route_to_broker` populates `HandoffPacket.transcript`.
- A Go test in `services/voice` for the Rails-call path (stubbed HTTP).
- Targets: brain 241 unchanged; Rails 304 → +~20; Go builds clean.

## Out of scope

- Full Twilio-signature / SendGrid DKIM validation (shared-secret token now;
  documented seam).
- Durable brain-side conversation memory (the Rails `Conversation` is the durable
  record; brain memory stays in-process, warm via `min_machines_running = 1`).
- Media/MMS, attachments, delivery-receipt callbacks.

## Migration notes

One migration `create_conversations_and_messages` (two tables + a unique index on
`conversations.contact` + FK). Local Postgres is not running; mirror into
`db/schema.rb` (version bump) as in prior pillars. No proto regen. New ENV:
`TWILIO_FROM`, `SENDGRID_FROM`, `INBOUND_WEBHOOK_TOKEN`, `DOMAIN_URL` (voice) —
all optional; unset keeps SMS/Email simulated and inbound off.
