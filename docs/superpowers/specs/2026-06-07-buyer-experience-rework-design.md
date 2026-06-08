# Buyer Experience Rework — Design

Date: 2026-06-07
Status: Implemented
Cluster: 1 of 2 (Cluster 2 = closing-orchestration wiring, separate spec)

## Problem

The buyer listing detail page (`buyer/listings/show.html.erb`) stacks **11 sections**
— photos, price, key facts, Make-an-offer, Schedule, Neighborhood pulse,
What-the-photos-show, Cross-source check, About, Recent nearby sales, footer.
It overwhelms. Three of those are always-on analysis cards that most browsers
don't need until they ask.

Separately, buyer **intent qualification** (requirement #5) is captured by two
checkboxes — `Pre-approved` and `Move ≤30 days` — wedged into the Ask Atlas
sidebar (`shared/_agent_sidebar.html.erb`), visible only when signed in. They
POST per-message to `Agent::MessagesController#create`, which calls
`current_visitor.record_engagement` → `IntentTriage`. This is awkward: a checkbox
on every message is the wrong home for what is really **profile** data.

The Ask Atlas sidebar is also a bare text box — no suggested prompts to guide a
new visitor toward the agent's strengths.

## Goals

1. Slim the listing page to essentials; surface analysis on demand through Atlas.
2. Give Atlas **suggested-prompt chips** that answer with the *same cited data*
   the removed cards showed — directly serving the "glass box" demo.
3. Move buyer qualification into an **optional buyer profile** captured after
   sign-in; delete the two sidebar checkboxes; rewire `IntentTriage` to read it.

## Invariants preserved

- **Zero external calls on the request path** — every Atlas insight reads DB/cache
  (`PriceCheck`, `CrossSourceReconciliation`, `PhotoAnalysis`, `@comps`,
  `ShowingScheduler`). No RentCast, no Anthropic on a web request.
- **Red-flags are broker-only** — the "What the photos show" insight uses
  `PhotoAnalysis.feature_findings` exclusively; `review_findings` are never sent
  to a buyer.
- **Neutral-signals-only triage** — the profile form collects only
  financing-pre-approval / move-timeline / budget, all already on the
  `IntentTriage::NEUTRAL_SIGNALS["buyer"]` allow-list. No protected-class fields.

## Design

### A. Slim the listing page

`buyer/listings/show.html.erb` keeps: photos · price · key facts ·
**Make an offer** · **Schedule a showing** (kept on-page — it is an interactive
booking widget, not an info dump) · short *About* · footer attribution.

**Removed as always-on cards:** Neighborhood pulse, What-the-photos-show,
Cross-source check, Recent nearby sales. `Buyer::ListingsController#show` stops
eager-assembling `@reconciliation` / `@photo_analysis` / `@comps` purely for
render (kept only if still needed by the scheduler/price paths; otherwise
removed). That data now flows through Atlas on demand.

### B. Atlas suggested-prompt chips + `ListingInsights` responder

The sidebar renders a row of **chips** above the ask box. Each chip submits a
known `insight` key plus the current `listing_id`. Chips are shown to all
visitors (insights are general, non-personal).

| Chip label | `insight` key | Reuses | Returns (cited) |
|---|---|---|---|
| Is this fairly priced? | `price` | `PriceCheck` | AVM estimate vs asking + cross-source reconciliation |
| How's this neighborhood? | `neighborhood` | `CrossSourceReconciliation.for` | market signal (hot/balanced/cool), median, $/sqft, days-on-market |
| What do the photos show? | `photos` | `PhotoAnalysis#feature_findings` | features + photo-derived condition (**feature findings only**) |
| Recent nearby sales | `comps` | comp pool (`ListingComps`/existing `@comps` source) | up to 3 comparable sales |
| Can I tour this week? | `tour` | `ShowingScheduler.available_slots` | open slots; links to the on-page scheduler |

New service **`ListingInsights`** (Rails, `app/services/listing_insights.rb`):
`ListingInsights.new(listing:).answer(key:, visitor:)` → a small value object
`Answer(title, body_html_or_lines, sources, available)`. It maps each key to the
existing service and formats a cited agent message. Unknown key ⇒ `available:
false` (caller falls through to the brain).

`Agent::MessagesController#create` routing:
- If `params[:insight]` is a known `ListingInsights` key **and** `listing_id`
  resolves → render the insight answer as the agent reply (no brain call).
- Otherwise (free text) → unchanged: brain `Orchestrate`.

The chip click is a normal sidebar submit (Stimulus `agent-sidebar` controller)
carrying `insight` + `listing_id`; the existing turbo-stream append renders the
answer in `#agent-messages`.

### C. Buyer profile replaces the checkboxes

- Sign-in stays name + email (frictionless) — `SessionsController#create`
  unchanged.
- New **`Buyer::ProfilesController`** + `/buyer/profile` (`edit`/`update`) with
  optional fields:
  - financing **pre-approved?** (yes / no / unsure)
  - **move-in timeline** (ASAP / ≤30 days / 1–3 months / just browsing)
  - **budget** (optional, USD)
- Stored on `Visitor` as structured nullable columns:
  `pre_approved:boolean`, `move_timeline_days:integer`, `budget_cents:integer`.
  (Chosen over reusing `engagement_signals` JSON for clear, editable profile
  semantics.) `engagement_signals` is retained for the seller side / address
  context.
- Entry points: a post-sign-in CTA ("Complete your buyer profile for tailored
  help") and an Atlas nudge link when a signed-in visitor has an empty profile.
- **`IntentTriage` rewired**: a thin adapter `Visitor#buyer_signals` builds the
  signals hash from the columns (`{"preapproval" => pre_approved, "move_timeline_days"
  => move_timeline_days, "budget" => budget_cents}`), and triage is recomputed on
  profile `update`. The high-intent rule is unchanged (pre-approved **and**
  ≤30 days ⇒ high-intent ⇒ existing `route_to_broker`, still one-shot via
  `handed_off`).
- **Delete** the two `check_box_tag` lines and the per-message `triage_visitor`
  checkbox path in `Agent::MessagesController`. (Address context capture stays.)

## Components & boundaries

- `ListingInsights` — pure mapper, no IO of its own beyond the services it calls;
  unit-testable with a stubbed listing. One responsibility: key → cited answer.
- `Buyer::ProfilesController` — REST `edit`/`update` on the current visitor's
  profile; thin.
- `Visitor` — gains profile columns + `buyer_signals` adapter + recompute hook.
  `record_engagement` stays for seller/address; the buyer checkbox branch is
  removed.
- `Agent::MessagesController` — gains the insight-routing branch; loses the
  checkbox triage branch.

## Data flow

1. Visitor opens a listing → slim page (no analysis cards).
2. Clicks a chip → sidebar submit with `insight`+`listing_id` →
   `Agent::MessagesController#create` → `ListingInsights.answer` → cited reply in
   `#agent-messages`. (DB-only.)
3. Visitor opens `/buyer/profile`, fills timeline/pre-approval/budget → `update`
   persists columns → `IntentTriage` recompute → high-intent ⇒ broker handoff.

## Error handling

- Missing insight data (e.g. no `PhotoAnalysis` row) → answer with
  `available: false` and a graceful "I don't have a photo read for this home yet"
  line; never a 500.
- Unknown `insight` key or unresolvable `listing_id` → fall through to the brain.
- Profile update validation: budget non-negative integer; timeline from a fixed
  enum; pre-approved tri-state. Invalid ⇒ re-render `edit` 422.

## Testing

- `ListingInsightsTest` — one case per chip key; explicit assertion that the
  `photos` answer contains **no** `review_findings` labels (safety invariant).
- `Agent::MessagesControllerTest` — known `insight` key routes to the insight
  (no brain call, stub asserts brain not invoked); free text routes to brain.
- `VisitorTest` / `Buyer::ProfilesControllerTest` — profile `update` persists
  columns; pre-approved + ≤30 days ⇒ `intent` high ⇒ `route_to_broker` fired once;
  pre-approved only ⇒ not high.
- View/system check — slimmed `show` no longer renders the four removed card ids
  (`#neighborhood-pulse`, `#photo-analysis`, cross-source block, comps); chips
  present in the sidebar.
- Suite stays green (brain 238 unaffected; Rails 283 + new cases).

## Out of scope (this spec)

- Closing-orchestration wiring (#9) — Cluster 2, separate spec.
- Neighborhood **news** signal (#1) and omnichannel shared thread (#4) — later.
- Any change to the seller workspace or broker dashboard beyond the existing
  handoff path.

## Migration notes

Local Postgres is not running; the migration for the three `Visitor` columns is
hand-mirrored into `db/schema.rb` (version bump) as in prior pillars. SQLite test
DB picks them up from schema.
