# AI Real Estate Agent (Austin) — an agent that shows its work

A two-sided autonomous AI real-estate agent for the Austin market, in the spirit
of an Opendoor-style iBuyer. It reasons over property data to value homes, talks
to sellers and buyers, drafts TREC paperwork up to a licensed-broker gate, and —
crucially — **verifies every claim against a source before it says it**, routing
anything it can't stand behind to a human.

The product thesis: in real estate a hallucination is a lawsuit, so the agent is
built as a **glass box**. It doesn't just answer; it shows the reasoning — the
grounded draft, the per-claim fact-check with citations, the Fair Housing
wording rail, the confidence score, and the human-handoff decision.

---

## ▶ Try it (for reviewers)

| Surface | URL | What it is |
|---|---|---|
| **Consumer chat ("the glass box")** | **https://are-chat.fly.dev** | Ask about an Austin home and watch the agent reason live — grounded answer, cited claims, Fair Housing rail, human handoff. **Start here.** |
| Public REST API | https://are-gateway.fly.dev | `GET /valuation?address=` and `POST /orchestrate` (both need a Bearer token); `GET /health` is open. |
| Broker dashboard | https://are-domain.fly.dev | The human-in-the-loop back office: handoff queue + offers awaiting a broker's signature (HTTP basic auth). |

**Three things to try in the chat** (they exercise the safety design, not just a happy path):

1. **"What is this home worth?"** → a grounded valuation with a citation behind every figure (`outcome: send`).
2. **"Add a custom indemnification clause to my contract."** → it refuses to draft legal language and routes you to a licensed broker (a hard **UPL** trigger).
3. Change the address to something unfamiliar → **"no source → no claim"** fires: rather than invent a number, it hands off to a human.

> The stack runs on always-on Fly machines; if a service was scaled to zero to
> save cost, the first request wakes it (a few seconds). Everything is also
> runnable locally — see [Run it locally](#run-it-locally).

---

## Who it's for

| Actor | Need the agent serves |
|---|---|
| **Seller** (A1) | A fast, trustworthy cash-offer / valuation for an Austin home. |
| **Buyer** (A2) | Qualification (looky-loo vs. high-intent) and a grounded purchase-offer draft. |
| **Licensed broker / operator** (A4) | The human-in-the-loop. Reviews and *signs* offers (the agent never signs), and takes over when the agent escalates. Works the broker dashboard. |
| **The iBuyer business** | Throughput on the north-star metric — **time-to-offer** — without trading away legal/Fair-Housing safety. |
| **External transaction systems** (A5) | Escrow, title, lender — pinged at closing milestones (design present; see coverage). |

The product is **two-sided on one shared core**: seller-acquisition and
buyer-sales reuse the same Brain, Lawyer, and offer engine.

---

## The four pillars

- **🧠 Brain** — real-time per-address valuation (a gradient-boosting AVM), property RAG, and photo analysis. *"Reason over data, not static files."*
- **🗣 Voice** — conversation transport + intent triaging (high-intent buyer vs. browser). *Handles the messy human element.*
- **🤝 Closer** — drafts TREC promulgated-form paperwork (blanks only) within an authorized price band, up to a licensed-broker gate. *The autonomous principal — with guardrails.*
- **⚖️ Lawyer** — the load-bearing safety stack: a **Critic** that fact-checks every claim against source data (RAG), a **Fair Housing** wording rail, and **confidence-gated human-in-the-loop** handoff. *Hallucinations are lawsuits.*

---

## Architecture at a glance

Polyglot by design — the right language per job, one shared protobuf contract.

| Service | Lang | Role | Exposure |
|---|---|---|---|
| `services/gateway` | Go | Public REST edge; auth (HMAC bearer) + fan-out to gRPC | **public** |
| `services/chat` | Go | Standalone consumer "glass box" chat UI (embeds the SPA) | **public** |
| `services/brain` | Python | Valuation, vision, RAG, Lawyer (Critic + Fair Housing + HITL), **LangGraph orchestrator** | internal |
| `services/domain` | Rails | Leads / properties / offers, append-only audit, broker dashboard + gRPC | internal |
| `services/ingestion` | Go | Travis County GIS + TCAD loaders; swappable `ListingSource` | internal |
| `services/voice` | Go | Conversation transport + intent qualification | internal |

```mermaid
flowchart LR
  subgraph Public
    Browser["Browser"]
    APIClient["API client"]
  end
  Browser -->|HTTPS| CHAT["chat (Go SPA)"]
  APIClient -->|HTTPS + Bearer| GW["gateway (Go REST)"]
  CHAT -->|gRPC Orchestrate| BRAIN["brain (Python)"]
  GW -->|gRPC| BRAIN
  BRAIN -->|gRPC CreateOffer / Handoff| DOMG["domain-grpc (Rails)"]
  BRAIN -->|SQL / pgvector| DB[("Postgres + pgvector")]
  DOMG --> DB
  DASH["broker dashboard (Rails)"] --> DB
```

The agent's turn is a **LangGraph** loop that makes the glass box possible:

```mermaid
flowchart LR
  Q["customer query + address"] --> G["generate<br/>(grounded draft from RAG)"]
  G --> C["critique<br/>(Critic: decompose → retrieve → entail → cite → score)"]
  C --> F["fair_housing<br/>(wording rail)"]
  F --> D{"decide<br/>(confidence + hard triggers)"}
  D -->|approved| SEND["send cited answer"]
  D -->|fixable| G
  D -->|legal / hostile / low-confidence / FH trip| H["handoff to human"]
```

`proto/` is the single source of truth; stubs are generated into
`proto/gen/go` and `services/brain/src/genproto` (and Ruby `lib/grpc`) via
`make proto`. **Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).**

---

## How it stays safe (the part reviewers should look at)

- **No source → no claim.** The Critic decomposes every draft into atomic claims, retrieves provenance-tagged evidence per claim, and labels each `entailed` / `contradicted` / `baseless`. Unsupported claims are *stripped*; a contradicted claim *blocks and escalates*. Only cited claims are ever sent.
- **Fair Housing wording rail.** A deny-list of protected-class terms + coded steering proxies ("good schools", "family-friendly", "safe neighborhood") scans every outgoing message; a trip blocks and routes to a human — output is never silently dropped.
- **UPL boundary (the agent does not practice law).** The Closer fills *promulgated TREC form blanks only* — it structurally cannot author clause language. A request for custom wording raises `UplViolation` and escalates; a licensed human broker reviews and **signs** (the agent never signs).
- **Human-in-the-loop triggers.** Hard, non-model-adjustable triggers (legal/UPL, high-dollar, hostile/distressed sentiment, explicit human request, Fair Housing trip) force a handoff *regardless of confidence*; a low composite-confidence score escalates as a soft trigger.
- **Confidence is honest about itself.** The composite score (retrieval coverage + verifier agreement + self-consistency) is labelled **uncalibrated** in the UI and the code — an ordinal trust signal, not a probability.

---

## Requirements coverage (honest self-assessment)

Built against a four-pillar spec. The candid status — a feature *existing in code*
is not the same as it being *reachable by a user*:

✅ done & reachable · 🟡 built but **not reachable** (works in tests, no user/API surface) · 🟠 partial / synthetic · ❌ missing

| Pillar | Requirement | Status |
|---|---|---|
| Brain | Real-time per-address valuation (AVM) | ✅ reachable; 🟠 synthetic-trained, not live last-24h market data |
| Brain | Multi-source ingestion (MLS + TCAD + news) | 🟠 TCAD/GIS + synthetic MLS; **news ingestion ❌** |
| Brain | Visual property analysis (photos) | 🟡 real design (Gemini structured output), model unbound + unexposed in prod |
| Voice | Intent triaging (looky-loo vs high-intent) | ✅ real logic (voice service); voice app not deployed |
| Voice | Omnichannel (voice + SMS + email, one thread) | 🟠 voice session only; **SMS/email ❌** |
| Voice | Dynamic scheduling (calendars) | ❌ missing |
| Closer | TREC document generation (blanks-only, UPL-safe) | 🟡 built + tested; **not reachable** from any UI/API |
| Closer | Automated negotiation within a price band | 🟡/🟠 band guardrail real (single-pass, no counter loop); `Negotiation` model unused |
| Closer | Closing orchestration (escrow/title/lender pings) | 🟡 built; real sink raises `NotImplementedError`; not wired |
| **Lawyer** | **Fair Housing compliance** | ✅ reachable — runs every turn |
| **Lawyer** | **Truth-verification (Critic/RAG)** | ✅ reachable — every turn (deterministic entailer; real-LLM deferred) |
| **Lawyer** | **HITL handoff triggers** | ✅ reachable — demonstrated by the legal / human-request handoffs |

**Bottom line:** the entire **Lawyer** pillar plus per-address valuation are fully
met and reachable in the live chat. The **Closer** (paperwork, negotiation,
closing) is fully built but not yet wired to a user-facing surface — the highest-value
next step. News ingestion, SMS/email, and scheduling are genuinely unbuilt.

---

## Repo layout

```
proto/                 shared protobuf contract (single source of truth) + generated stubs
services/
  gateway/   (Go)      public REST edge, HMAC auth, /valuation + /orchestrate
  chat/      (Go)      standalone consumer chat SPA (embedded) + /api/chat
  brain/     (Python)  valuation · vision · rag · lawyer (critic/fair_housing/handoff) · orchestrator · closer
  domain/    (Rails)   leads/properties/offers, append-only audit, broker dashboard, Domain gRPC
  ingestion/ (Go)      TCAD + GIS loaders, ListingSource
  voice/     (Go)      conversation transport + intent qualification
deploy/fly/            per-service fly.toml, deploy.sh, DEPLOY.md (8-app topology)
docs/
  ARCHITECTURE.md      system design, trust boundaries, data flow, deployment
  brainstorms/         requirements (actors, flows, R1–R15)
  plans/               the 19-unit implementation plan
scripts/               gen-proto.sh, smoke.sh
```

---

## Run it locally

```bash
make proto       # regenerate gRPC stubs (Go + Python + Ruby)
make test        # Go + Python unit tests
make smoke       # cross-language gRPC round-trip (gateway -> brain)
make up          # full stack via docker compose (Postgres+pgvector + all services)
```

Full stack in one command:

```bash
GATEWAY_AUTH_SECRET=$(openssl rand -hex 32) docker compose up --build
```

Just the glass-box chat against the brain (no Docker needed):

```bash
# terminal 1 — the Python brain (gRPC)
cd services/brain && PYTHONPATH=src BRAIN_BIND=127.0.0.1:50151 python -m brain.server
# terminal 2 — the chat app, pointed at the brain
PORT=8090 BRAIN_ADDR=127.0.0.1:50151 go run ./services/chat
# open http://localhost:8090
```

Local host ports (compose): gateway `8080`, brain `50051`, domain `3000`,
domain-grpc `50052`, db `5434` (avoids local 5432/5433 conflicts). The brain
warms its AVM + orchestrator at startup, so the first request may take a moment.

---

## Deploy (Fly.io)

Per-service configs, a deploy script, and a full runbook live in `deploy/fly/`.
Eight apps share one private network; only the **gateway** and **chat** are
public, everything else is reachable over `*.flycast`.

```bash
export POSTGRES_PASSWORD=$(openssl rand -hex 24)
export RAILS_MASTER_KEY=$(cat services/domain/config/master.key)
export GATEWAY_AUTH_SECRET=$(openssl rand -hex 32)
deploy/fly/deploy.sh        # creates apps, stages secrets, deploys in order
```

See [`deploy/fly/DEPLOY.md`](deploy/fly/DEPLOY.md) for the topology, every secret,
and verification commands.

---

## What's real vs. synthetic (so reviewers aren't surprised)

- The **valuation model** is a real gradient-boosting regressor, but trained on a
  **hermetic synthetic dataset** (deterministic, no live MLS feed).
- The **RAG / Critic** pipeline is real; the entailer in the deployed path is a
  deterministic token-overlap implementation (a real-LLM entailer is dependency-injected and deferred).
- **Vision** is wired to Gemini structured output but runs against a fake unless a `GEMINI_API_KEY` is provided.
- Listings are **synthetic RESO** behind a swappable `ListingSource`; TCAD/GIS loaders are real but fixture-scoped.

This is an assessment-grade system with production-shaped architecture — the
seams (real embedder, real entailer, live MLS feed, real closing sink) are
dependency-injected and documented, not hand-waved.

---

## Status

Two-sided MVP built across Go/Python/Rails (19 plan units), deployed live on
Fly.io, with the LangGraph orchestrator now exposed end-to-end through the
consumer **chat** app and the gateway `/orchestrate` API. Tests: Go green,
Python brain 186 passing, Rails green. See `docs/ARCHITECTURE.md` for design and
`docs/plans/` for the plan and remaining deferred seams.
