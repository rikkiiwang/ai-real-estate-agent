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
make up          # full stack via docker compose (Postgres+pgvector + services)
```

## Status

Foundation in progress — see `docs/plans/` and the task tracker. Built so far:
shared proto contract, Go gateway/ingestion/voice skeletons, Python Brain
(valuation placeholder + Critic stub), cross-language round-trip, Postgres+
pgvector compose, CI.
