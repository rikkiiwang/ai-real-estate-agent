# AI Real Estate Agent

A two-sided autonomous AI real estate agent for the Austin market, built on one
shared core. Two deep pillars — a **Brain** (real-time valuation + property
intelligence) and a **Lawyer** (claim verification, Fair Housing, confidence-
gated human handoff) — anchor a thin **Closer** and **Voice**.

See `docs/brainstorms/` for requirements and `docs/plans/` for the
implementation plan.

## Architecture (polyglot)

| Service | Language | Role |
|---|---|---|
| `services/gateway` | Go | Public REST edge; authenticates + fans out to gRPC |
| `services/ingestion` | Go | Travis County GIS + TCAD loaders; swappable ListingSource |
| `services/voice` | Go | Single-channel conversation transport |
| `services/brain` | Python | Valuation, vision, Lawyer (Critic + Fair Housing), RAG, orchestrator |
| `services/domain` | Rails | Leads / properties / offers, audit log, broker handoff dashboard (U9) |

`proto/` is the single cross-language contract; stubs are generated into
`proto/gen/go` and `services/brain/src/genproto` via `make proto`.

## Develop

```bash
make proto       # regenerate gRPC stubs
make test        # Go + Python unit tests
make smoke       # cross-language gRPC round-trip (gateway -> brain)
make up          # full stack via docker compose (Postgres+pgvector + all services)
```

## Run the full stack locally

```bash
GATEWAY_AUTH_SECRET=$(openssl rand -hex 32) docker compose up --build
```

Brings up all seven services: Postgres+pgvector, the Python brain, the Go
gateway/ingestion/voice, and the Rails domain (broker dashboard + gRPC server).
Migration runs on boot (the `domain` web service is the single migrator; the
`domain-grpc` service waits for it). Exposed host ports:

| Service | Host port | What |
|---|---|---|
| gateway | 8080 | public REST edge (auth'd; needs `GATEWAY_AUTH_SECRET`) |
| brain | 50051 | gRPC (valuation, verification) |
| domain | 3000 | broker dashboard (`/up` health) |
| domain-grpc | 50052 | gRPC Domain service (CreateLead, EnqueueHandoff) |
| db | 5434 | Postgres+pgvector (5434 avoids local 5432/5433 conflicts) |

The brain warms its AVM at startup; the first request may take a few seconds.

## Status

Full two-sided MVP built (19 plan units) and verified across Go/Python/Rails.
The compose stack boots end-to-end — a live `CreateLead` call reaches the Rails
domain over gRPC and persists. See `docs/plans/` for the plan and the deferred
seams (e.g. the `CreateOffer` RPC binding the Python Closer to the Rails offer
queue).
