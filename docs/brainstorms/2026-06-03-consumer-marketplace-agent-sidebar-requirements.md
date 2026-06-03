---
date: 2026-06-03
topic: consumer-marketplace-agent-sidebar
---

# Consumer Marketplace with Agent Sidebar — Requirements

## Summary

Add a traditional Austin real-estate browsing site — searchable by region and
price, with photos and side-by-side comparison — and embed the existing AI
agent as a context-aware **sidebar** inside two workspaces, **Buyer** and
**Seller**, that one logged-in person can use in parallel. The agent drives
search into the listing view, walks a buyer from a listing through
comps / rate / tax / monthly-payment to a submitted offer and an in-app
contract draft, and reuses the existing valuation + Closer + Lawyer backend on
the seller side. Every number the agent shows carries a source.

## Problem Frame

The agent's reasoning, valuation, verification (Critic), paperwork (Closer),
and safety (Lawyer) capabilities largely exist in the backend, but they are
exposed only as a JSON API, a broker dashboard, and a single agent-only chat
surface. A first-time consumer landing on the product has no familiar way to
*browse, filter, and compare* homes — the things a real estate shopper expects
before they ever want to talk to an assistant. Facing only an agent, a user
can't sift inventory or compare options, so the capable backend reads as
invisible. The fix is to restore the conventional listing-site surface and let
the agent operate *alongside* it as an assistant, not *instead* of it.

## Key Decisions

- **Two workspaces, not role-gated login.** A single identity holds both a
  Buyer and a Seller tab and can work in both in parallel. Login does not force
  a buyer-or-seller choice. This is simpler auth and lets one demo user play
  both sides of a transaction.
- **Buyer side is net-new and deep; seller side is a thin wrapper.** The buyer
  journey (browse → compare → offer with rate/comps/tax/monthly → contract) is
  built fresh. The seller journey reuses the existing valuation + Closer +
  Lawyer cash-offer path with a light UI over it.
- **Static scraped seed, not a live feed.** ~20 real Austin listings are
  scraped once (real addresses, real sale-comp references, curated real photo
  URLs) and stored as static seed data, provenance-labeled in the UI. No live
  scraping runs at request time — real-feeling, controllable, and avoids
  live-scraping / ToS exposure.
- **Dated static values for rate, tax, and comps.** Mortgage rate, property
  tax rate, and comps are dated static values shown with their source and
  as-of date (e.g., "rate as of <date>, Freddie Mac PMMS"), not live APIs.
- **Lightweight login by default.** Name/email, no password, single identity.
  A real account system is out of scope for this iteration.
- **Contract is an in-app draft; UPL boundary preserved.** Reuse the existing
  TREC blanks-only Closer. The contract is delivered in-app to both parties as
  a draft for review — no e-signature, legally-binding execution, or money
  movement.
- **The agent augments the listing site, it never replaces it.** The
  conventional browse/search/compare infrastructure is first-class and must
  not be removed.

## Actors

- A1. **Consumer (dual-workspace user)** — a single logged-in person who can
  operate both the Buyer and Seller workspaces in parallel.
- A2. **AI Agent (sidebar)** — the context-aware assistant backed by the
  existing brain/orchestrator; drives search, builds the offer decision
  bundle, and generates the contract draft.
- A3. **Licensed broker (HITL)** — existing human-in-the-loop; reviews/approves
  offers and receives handoffs when the agent escalates.
- A4. **Counterparty (seller or buyer on the other side of a deal)** — receives
  an offer and, on acceptance, the in-app contract draft.

## Requirements

**Listing catalog & browse/search**

- R1. The site presents a browsable catalog of ~20 real Austin properties, each
  with address, asking price, beds, baths, square footage, neighborhood/region,
  and at least one photo.
- R2. Users can filter the catalog by region (neighborhood/area) and price
  range, and compare listings (list view that supports side-by-side comparison).
- R3. Listing data is seeded once from scraped real listings and stored as
  static seed data; the UI labels it as sample data with its provenance. No
  live scraping service runs at request time.

**Agent sidebar**

- R4. Both the Buyer and Seller workspaces render the agent as a persistent side
  panel, shown alongside the main listing/grid view rather than replacing it.
- R5. The agent is context-aware of the user's current view (active workspace
  and, on the buyer side, the listing or search currently in focus) and also
  responds to free-text prompts.
- R6. When a user asks the agent about an area or price range, the agent runs
  the search and surfaces matching results into the traditional list view for
  browsing and comparison — the agent drives the list, it does not replace it.

**Buyer offer journey**

- R7. When a buyer signals intent to offer on a listing, the agent presents a
  decision bundle: current mortgage rate, nearby sale comps, the annual property
  tax rate, and the resulting estimated monthly payment.
- R8. The estimated monthly payment is computed from stated assumptions (offer
  amount, down-payment %, rate, term, tax), and those assumptions are shown
  alongside the number.
- R9. The buyer can submit an offer to the seller through the agent; the offer
  is recorded and routed for broker review/approval before it is binding.

**Seller workspace**

- R10. The seller workspace lets a seller request a valuation and a platform
  cash offer for their address, reusing the existing valuation + Closer + Lawyer
  backend.
- R11. Seller-side outputs (valuation, cash offer) carry the same
  citation/verification treatment and HITL handoff behavior the agent already
  applies elsewhere.

**Contracts & in-app delivery**

- R12. When an offer is accepted, the agent generates a contract (reusing the
  existing TREC blanks-only Closer) and delivers it in-app to both parties as a
  draft document.
- R13. The contract is a draft for review only — no e-signature, legally-binding
  execution, or money movement is in scope.

**Provenance (cross-cutting)**

- R14. Every number or claim the agent surfaces — valuation, mortgage rate,
  comps, tax rate, monthly payment — carries a visible source/citation, reusing
  the existing Critic "no source → no claim" machinery. Static values (rate,
  tax) display their as-of date and source.

**Identity & workspaces**

- R15. A lightweight login (name/email, no password) creates a single identity;
  after login the user has both a Buyer and a Seller workspace available
  simultaneously and can work in both in parallel.
- R16. The agent's assistant mode follows the active workspace (buyer-assist vs
  seller-assist) while both share the one identity/session.

## Key Flows

- F1. **Buyer: browse to contract**
  - **Trigger:** A1 opens the Buyer workspace.
  - **Actors:** A1, A2, A3, A4
  - **Steps:** Browse/filter the catalog (or ask the agent, which surfaces
    results into the list) → focus a listing → signal intent to offer → agent
    shows the decision bundle (rate / comps / tax / monthly payment, each cited)
    → submit offer → broker review/approval (A3) → on acceptance, agent
    generates the contract draft and delivers it in-app to both parties.
  - **Covers:** R1, R2, R5, R6, R7, R8, R9, R12, R14

- F2. **Seller: valuation & cash offer**
  - **Trigger:** A1 opens the Seller workspace and enters an address.
  - **Actors:** A1, A2, A3
  - **Steps:** Request valuation + platform cash offer → agent returns a cited
    valuation and offer, or escalates to the broker on a hard trigger
    (legal/UPL, high-dollar, fair-housing, low confidence) → output reuses the
    existing Closer/Lawyer path.
  - **Covers:** R10, R11, R14

- F3. **Agent-driven search surfacing**
  - **Trigger:** A1 asks the agent (in either workspace) about an area or price.
  - **Actors:** A1, A2
  - **Steps:** Agent parses the request → runs the catalog search → renders the
    matching listings into the traditional list view, with a one-line cited
    rationale → user browses/compares normally.
  - **Covers:** R5, R6, R14

## Acceptance Examples

- AE1. **Covers R7, R8, R14.** Given a buyer focused on a $625,000 listing, when
  they signal intent to offer, then the agent shows the mortgage rate (with
  as-of date + source), 2–3 nearby comps (each cited), the annual tax rate (with
  source), and an estimated monthly payment with its assumptions (down-payment
  %, rate, term) displayed beside it.
- AE2. **Covers R9.** Given a submitted buyer offer, when it is recorded, then it
  is routed to the broker queue for review/approval and is not treated as
  binding until approved.
- AE3. **Covers R12, R13.** Given an accepted offer, when the agent generates the
  contract, then it produces a TREC blanks-only draft (no authored clauses),
  delivers it in-app to both parties, and labels it a draft for review — not an
  executed agreement.
- AE4. **Covers R6.** Given a buyer asks "show me 3-bed homes under $700k in
  Mueller," when the agent answers, then the matching listings appear in the
  traditional list view (filterable/comparable), not only as prose in the chat.
- AE5. **Covers R14.** Given any agent-surfaced number with no supporting source,
  when the Critic evaluates it, then the agent withholds the claim or escalates
  rather than presenting an unsourced figure.

## Scope Boundaries

**Deferred for later**

- Real account system (passwords, email verification, sessions across devices).
- Live MLS feed / continuous scraping service.
- Real-time mortgage-rate API.
- Seller-side feature parity with the buyer depth.
- Other PRD-gap channels: news ingestion, SMS/email/voice.

**Outside this product's identity (for this iteration)**

- A legal-execution / closing platform — no e-signature, no escrow, no money
  movement. The contract is a draft.
- A live listing aggregator — inventory is a curated static sample, not a
  real-time market feed.

## Dependencies / Assumptions

- ~20 Austin listings can be scraped once for sample/demo use; data is stored as
  static seed and provenance-labeled. Photos/data are treated as sample,
  source-attributed (ToS/copyright caveat acknowledged).
- Mortgage rate source is a dated static value (e.g., Freddie Mac PMMS); tax
  rate is the Travis County / TCAD rate; comps come from the scraped sample.
- The `Property` model (currently `address` + `state` only) must be extended to
  carry price, beds, baths, square footage, region, photo URL(s), and comp
  references. Exact schema is an implementation decision deferred to planning.
- Reuses the existing `Conversation.Orchestrate` RPC, brain/orchestrator,
  Closer (TREC blanks-only), Critic, fair-housing rail, and HITL handoff.

## Outstanding Questions

**Resolve before planning**

- None blocking — the defaults above (lightweight login, static dated values,
  in-app contract draft) were confirmed during brainstorming.

**Deferred to planning**

- Persistence/schema for listings, buyer offers, and accepted-offer contracts.
- How the agent receives the user's current page/listing context (the
  context-awareness transport into the brain).
- Comp-matching logic (how nearby comps are selected for a given listing).
- Which external source the ~20 sample listings are scraped from.

## Success Criteria

- A first-time user can browse, filter by region/price, and compare listings
  without ever talking to the agent.
- A buyer can go from a listing to a submitted, broker-routed offer with a fully
  cited decision bundle (rate, comps, tax, monthly payment).
- A seller can get a cited valuation + cash offer that reuses the existing
  backend and escalates correctly on hard triggers.
- An accepted offer yields an in-app TREC blanks-only contract draft delivered
  to both parties.
- No agent-surfaced number appears without a source; static values show their
  as-of date.
