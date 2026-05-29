---
date: 2026-05-29
topic: ai-real-estate-agent
---

# AI Real Estate Agent — Requirements

## Summary

A two-sided, autonomous AI real estate agent for the Austin market, built on
one shared core. A **Brain** values homes and surfaces property intelligence
from real public data plus synthetic listings; a **Lawyer** verifies every
customer-facing claim against source data and hands off to a human when its
confidence drops. Seller (cash-offer) and buyer (home-shopping) experiences
are two thin front doors onto that shared core. The primary metric is
**time to offer**.

---

## Problem Frame

Traditional real estate runs on high-latency, person-to-person communication
over fragmented data. A homeowner who wants to sell, or a person who wants to
buy, waits days for a human agent to gather records, form a price, and produce
paperwork — and pays a 5–6% commission for the privilege. The latency is not
just annoying; in real estate, elapsed time is direct cost (interest, taxes,
insurance, carry).

The opportunity is to collapse that latency with software that can reason over
live-ish data and act, not just chat. The hard part is trust: in real estate,
a confident-but-wrong statement is a legal and financial liability, not a
harmless hallucination. Anything autonomous here only ships if the claims it
makes are grounded and its limits are known. That tension — autonomy that is
fast *and* safe to let loose — is the core of this product.

---

## Key Decisions

- **Two-sided on one shared core.** Seller-acquisition and buyer-sales are
  served by the same Brain, offer engine, and Lawyer. "Both" is affordable
  only because the expensive parts are shared; we are not building two
  products. The same property can flow through the loop (acquired from a
  seller, then resold to a buyer) — see F3.

- **Brain and Lawyer are the deep pillars; Closer and Voice stay thin.** The
  Brain (valuation + intelligence) and the Lawyer (verification + compliance +
  handoff) are built to production depth because together they are the
  "this is not a chatbot" differentiator: *intelligence you can trust*. The
  Closer (offer/negotiation/closing) and Voice (conversation/channels) are
  functional-but-thin and sit behind interfaces so they can deepen later
  without rework.

- **Real public data + synthetic listings.** Genuinely real public sources
  (Austin TCAD tax/appraisal, public records) anchor credibility. Licensed
  MLS data — the one piece that is gated — is represented by realistic
  synthetic listings behind a swappable source interface, so a live feed can
  drop in later. This is the honesty line for the MVP: demonstrable and
  grounded, not yet transactable end-to-end.

- **Single north-star metric across both sides.** *Time to offer* measures
  both the seller cash-offer and the buyer purchase-offer draft. One metric,
  two variants. *(Assumption — flagged in Outstanding Questions.)*

- **One-property-loop demo spine.** The reference narrative is a single
  property moving through acquire → list → resell, exercising both front doors
  and the shared core in one story. *(Assumption — flagged in Outstanding
  Questions.)*

- **Polyglot stack treated as a hard constraint.** Go, Ruby, and Python are
  taken as required languages for the build. How responsibilities split across
  them is a planning decision, not a brainstorm one. *(Assumption — flagged in
  Outstanding Questions.)*

---

## Actors

- A1. **Seller** — a homeowner who wants a cash offer for their Austin home.
- A2. **Buyer** — a prospective buyer shopping for an Austin home.
- A3. **AI agent system** — the orchestrator plus its sub-agents (Brain, Voice,
  Closer) coordinated under the Lawyer's verification and guardrails.
- A4. **Human operator** — the HITL fallback who receives handoffs on low
  confidence, hostile sentiment, or out-of-band legal complexity.
- A5. **External transaction systems** — escrow, title, and lender
  counterparts. Simulated for the MVP behind interfaces.

---

## Key Flows

- F1. **Seller cash-offer**
  - **Trigger:** A seller (A1) submits an address and intent to sell.
  - **Steps:** Brain ingests TCAD + public records + comparable (synthetic)
    listings → produces a real-time valuation → Closer drafts a cash
    acquisition offer → Lawyer's Critic verifies every claim against source
    data → offer is delivered, or escalated to A4 if confidence is low.
  - **Outcome:** A grounded cash offer, with time-to-offer recorded.
  - **Covered by:** R1, R2, R4, R8, R11, R13, R15

- F2. **Buyer home-shopping**
  - **Trigger:** A buyer (A2) expresses interest via the conversation channel.
  - **Steps:** Voice qualifies intent (looky-loo vs high-intent) → Brain
    surfaces matching properties and intelligence (incl. photo analysis) →
    Closer drafts a purchase offer → Critic verifies before anything reaches
    the buyer.
  - **Outcome:** A qualified buyer with a grounded purchase-offer draft.
  - **Covered by:** R3, R5, R6, R8, R11, R12, R15

- F3. **Full loop on one property (demo spine)**
  - **Trigger:** A property acquired via F1 becomes available to sell.
  - **Steps:** The acquired property is listed and flows into F2, demonstrating
    acquire → list → resell on a single property through the shared core.
  - **Outcome:** End-to-end Opendoor loop shown on one address.
  - **Covered by:** R14 (and the F1/F2 requirements above)

- F4. **Critic verification loop**
  - **Trigger:** Any agent prepares a customer-facing message or claim.
  - **Steps:** Critic checks each claim against source data (RAG); unverifiable
    claims are blocked, corrected, or escalated; only verified content sends.
  - **Outcome:** No unverified claim reaches a customer.
  - **Covered by:** R11

- F5. **HITL handoff**
  - **Trigger:** Confidence score below threshold, hostile sentiment, or legal
    complexity beyond scope.
  - **Steps:** The system pauses autonomous action, packages context, and hands
    off to A4.
  - **Outcome:** A human takes over with full context; no silent failure.
  - **Covered by:** R13

---

## Requirements

### The Brain — market intelligence (deep)

- R1. The agent produces a real-time valuation for any Austin address.
- R2. The agent ingests and cross-references multiple sources: real Austin TCAD
  tax/appraisal data and public records, synthetic MLS-style listings behind a
  swappable source interface, and neighborhood-level signals.
- R3. The agent analyzes property photos to identify high-value features and
  potential red flags, surfacing findings as grounded claims (subject to R11).
- R4. The valuation reflects recent market activity, not only static records.

### The Voice — engagement & qualification (thin)

- R5. The agent triages intent, distinguishing low-intent browsers from
  high-intent parties, on both seller and buyer sides.
- R6. The agent holds a coherent conversation over a single channel for the
  MVP, preserving thread/context, architected so additional channels (voice,
  SMS, email) can be added without rework.
- R7. The agent can propose and book tours or inspections against availability
  without double-booking. *(Thin — scheduling depth is minimal for MVP.)*

### The Closer — transaction logic (thin)

- R8. The agent generates offers from negotiation inputs: a cash acquisition
  offer on the seller side and a TREC-style purchase-offer draft on the buyer
  side.
- R9. The agent negotiates within predefined financial guardrails (authorized
  band, opening vs. ceiling), never exceeding its mandate. *(Thin — counter
  logic is bounded, not open-ended.)*
- R10. The agent orchestrates closing milestones — pinging escrow, title, and
  lender counterparts as milestones are met. *(Thin — external systems are
  simulated behind interfaces for the MVP.)*

### The Lawyer — safety & compliance (deep)

- R11. A Critic agent verifies every customer-facing claim against source data
  (RAG) before the message is sent; unverifiable claims are blocked, corrected,
  or escalated.
- R12. The agent never uses protected classes (race, religion, national origin,
  etc.) in its reasoning or in neighborhood/property descriptions (Fair
  Housing).
- R13. The agent computes a confidence score and hands off to a human operator
  when confidence is low, sentiment turns hostile, or legal complexity exceeds
  scope.

### Cross-cutting

- R14. Seller and buyer flows are served by one shared core (Brain, offer
  engine, Lawyer); the same property can move acquire → list → resell.
- R15. Time-to-offer is instrumented as the primary metric, captured for both
  the seller cash-offer and the buyer purchase-offer variants.

---

## Acceptance Examples

- AE1. **Covers R11.**
  - **Given** the Brain has produced a valuation citing a roof replacement,
  - **When** the Closer drafts an offer that references the roof,
  - **Then** the Critic confirms the roof claim against source data before the
    offer is sent; if it cannot, the claim is removed or the offer is escalated.

- AE2. **Covers R12.**
  - **Given** a buyer asks "is this a good neighborhood for people like me?",
  - **When** the agent responds,
  - **Then** the response describes only protected-class-neutral attributes
    (schools, amenities, price trends) and never infers or references a
    protected class.

- AE3. **Covers R13.**
  - **Given** an autonomous negotiation in progress,
  - **When** the counterparty turns hostile or the required price exceeds the
    authorized band,
  - **Then** the agent stops autonomous action and hands off to a human with
    full context, rather than guessing.

- AE4. **Covers R9.**
  - **Given** an authorized band of "start at $470k, ceiling $485k",
  - **When** the counterparty counters at $480k,
  - **Then** the agent may accept or counter within the band, and never offers
    above $485k.

---

## Success Criteria

- Time-to-offer (seller cash-offer and buyer purchase-offer) is measured and
  materially faster than a human-mediated baseline.
- Zero unverified customer-facing claims reach a customer (every claim passes
  the Critic or is escalated).
- Zero Fair Housing violations in agent reasoning or output.
- HITL handoff triggers correctly on low confidence, hostile sentiment, and
  out-of-scope legal complexity — no silent failures.
- The same property can be demonstrated moving through acquire → list → resell
  on the shared core (the demo spine).

---

## Scope Boundaries

### Deferred for later

- Live, low-latency voice and live SMS/email gateways (MVP is single-channel).
- Live MLS feed and licensing (synthetic listings behind a swappable source).
- Real escrow / title / lender integrations and e-signature execution (closing
  is simulated milestones).
- Geographies beyond Austin.

### Outside this product's identity

- A human-in-the-loop-by-default assistant. This is autonomous-first; humans
  are the exception path (R13), not the default operator.
- A generic real-estate CRM or a plain chatbot. The differentiator is grounded
  autonomy, not conversation volume.
- A replacement for licensed legal counsel; the Lawyer enforces guardrails and
  verification, it does not give legal advice.

---

## Dependencies / Assumptions

- **Data access.** Austin TCAD tax/appraisal and public records are obtainable
  and usable; a synthetic listing generator stands in for MLS behind an
  interface. *(Verify TCAD access terms during planning.)*
- **Models.** A capable LLM for reasoning/conversation and a vision model for
  photo analysis (R3) are available.
- **Polyglot stack.** Go, Ruby, and Python are required; the responsibility
  split across them is decided in planning.
- **Single-property demo spine.** The acquire → list → resell narrative on one
  property is the reference flow.

---

## Outstanding Questions

### Resolve before / during planning

- **Demo spine confirmation.** Is one property through the full loop the
  intended narrative, or two independent seller/buyer flows? *(Defaulted to the
  loop.)*
- **Language constraint.** Is Go + Ruby + Python a hard requirement (polyglot
  architecture) or a free choice where one language for MVP speed is
  acceptable? *(Defaulted to hard constraint.)*
- **Metric scope.** Is a single time-to-offer metric spanning both sides
  acceptable, or should each side have its own target? *(Defaulted to one
  metric, two variants.)*
