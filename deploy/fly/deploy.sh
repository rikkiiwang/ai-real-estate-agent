#!/usr/bin/env bash
# Deploy the AI Real Estate Agent to Fly.io.
#
# Idempotent: creates apps/volumes/IPs if missing, stages secrets, then deploys
# every service in dependency order. Run from anywhere; it cd's to the repo root.
#
# Prereqs: authed flyctl (`fly auth login`), Docker running (for image builds),
# and the required secrets exported (see "Required secrets" below / DEPLOY.md).
#
# Usage:
#   POSTGRES_PASSWORD=... RAILS_MASTER_KEY=... GATEWAY_AUTH_SECRET=... \
#     [GEMINI_API_KEY=...] [REGION=dfw] [ORG=personal] \
#     deploy/fly/deploy.sh [service ...]
#
# With no service args, deploys the full stack. Otherwise deploys only the named
# services (e.g. `deploy/fly/deploy.sh gateway brain`), still creating apps as
# needed. Core stack: db domain domain-grpc brain gateway. Optional: ingestion voice.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
FLY_DIR="deploy/fly"

REGION="${REGION:-dfw}"
ORG="${ORG:-personal}"

ALL_APPS=(are-db are-domain are-domain-grpc are-brain are-gateway are-chat are-ingestion are-voice)
CORE=(db domain domain-grpc brain gateway chat)

# Which services to deploy (positional args, else the core stack).
TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=("${CORE[@]}")

require() { [ -n "${!1:-}" ] || { echo "ERROR: \$$1 is required (see DEPLOY.md)"; exit 1; }; }

fly_app() { # app name for a service key
  case "$1" in
    db) echo are-db;; domain) echo are-domain;; domain-grpc) echo are-domain-grpc;;
    brain) echo are-brain;; gateway) echo are-gateway;; chat) echo are-chat;;
    ingestion) echo are-ingestion;; voice) echo are-voice;;
    *) echo "unknown service: $1" >&2; exit 1;;
  esac
}

echo "→ Ensuring apps exist (org=$ORG)"
for app in "${ALL_APPS[@]}"; do
  fly apps create "$app" --org "$ORG" >/dev/null 2>&1 && echo "  created $app" || true
done

echo "→ Ensuring the Postgres volume + flycast addresses exist"
fly volumes list --app are-db 2>/dev/null | grep -q pgdata \
  || fly volumes create pgdata --app are-db --region "$REGION" --size 3 --yes
# Private flycast IPs for the internal services (no public exposure).
for app in are-db are-brain are-domain are-domain-grpc are-ingestion are-voice; do
  fly ips list --app "$app" 2>/dev/null | grep -qi private \
    || fly ips allocate-v6 --private --app "$app" >/dev/null 2>&1 || true
done
# Public shared IPs for the two consumer-facing apps: the REST gateway and the
# standalone chat web app. Everything else stays private over flycast.
for app in are-gateway are-chat; do
  fly ips list --app "$app" 2>/dev/null | grep -qiE "v4|global" \
    || { fly ips allocate-v4 --shared --app "$app" >/dev/null 2>&1 || true; \
         fly ips allocate-v6 --app "$app" >/dev/null 2>&1 || true; }
done

echo "→ Staging secrets"
require POSTGRES_PASSWORD
DB_RAG="postgres://realestate:${POSTGRES_PASSWORD}@are-db.flycast:5432/realestate"
DB_DOMAIN="postgres://realestate:${POSTGRES_PASSWORD}@are-db.flycast:5432/domain_production"

stage() { fly secrets set --stage --app "$1" "${@:2}" >/dev/null && echo "  staged secrets for $1"; }

for svc in "${TARGETS[@]}"; do
  case "$svc" in
    db)          stage are-db POSTGRES_PASSWORD="$POSTGRES_PASSWORD";;
    domain)      require RAILS_MASTER_KEY; stage are-domain RAILS_MASTER_KEY="$RAILS_MASTER_KEY" DATABASE_URL="$DB_DOMAIN";;
    domain-grpc) require RAILS_MASTER_KEY; stage are-domain-grpc RAILS_MASTER_KEY="$RAILS_MASTER_KEY" DATABASE_URL="$DB_DOMAIN";;
    brain)       stage are-brain DATABASE_URL="$DB_RAG" ${GEMINI_API_KEY:+GEMINI_API_KEY="$GEMINI_API_KEY"};;
    gateway)     require GATEWAY_AUTH_SECRET; stage are-gateway GATEWAY_AUTH_SECRET="$GATEWAY_AUTH_SECRET";;
    chat)        : ;; # talks to the brain over the private mesh; no secrets
    ingestion)   stage are-ingestion DATABASE_URL="$DB_RAG";;
    voice)       : ;; # no secrets
  esac
done

# Deploy order: db first, then the migrator (domain), then everything else.
deploy() {
  local svc="$1" app context config
  app="$(fly_app "$svc")"; config="$REPO_ROOT/$FLY_DIR/${svc}.fly.toml"
  case "$svc" in
    db)                 context="$FLY_DIR";;
    domain|domain-grpc) context="services/domain";;
    *)                  context=".";;          # brain + Go services build from repo root
  esac
  echo "→ Deploying $app (context=$context)"
  fly deploy "$context" --config "$config" --yes
}

ORDER=(db domain domain-grpc brain gateway chat ingestion voice)
for svc in "${ORDER[@]}"; do
  for t in "${TARGETS[@]}"; do
    [ "$svc" = "$t" ] && deploy "$svc"
  done
done

echo "✓ Done."
echo "  Public gateway (REST API): https://are-gateway.fly.dev  (verify: curl https://are-gateway.fly.dev/health)"
echo "  Consumer chat app:         https://are-chat.fly.dev      (the 'glass box' agent UI)"
