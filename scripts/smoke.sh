#!/usr/bin/env bash
# U1 cross-language verification: start the Python Brain (gRPC) and call it
# through the Go gateway (REST -> gRPC), asserting the round-trip works.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:$PATH:$(go env GOPATH 2>/dev/null)/bin"

# Ports are overridable to avoid colliding with other local dev servers.
BRAIN_PORT="${BRAIN_PORT:-50151}"
GW_PORT="${GW_PORT:-18080}"
BRAIN_BIND="[::]:${BRAIN_PORT}"
GATEWAY_ADDR=":${GW_PORT}"
BRAIN_ADDR="localhost:${BRAIN_PORT}"
export GATEWAY_AUTH_SECRET="${GATEWAY_AUTH_SECRET:-dev-smoke-secret}"
# The brain needs a Python with grpc + the brain deps; the stdlib python3 may
# lack them. Honour the same PYTHON override the Makefile uses
# (PYTHON=/opt/anaconda3/bin/python3 make smoke), defaulting to python3.
PYTHON="${PYTHON:-python3}"

cleanup() {
  [[ -n "${BRAIN_PID:-}" ]] && kill "$BRAIN_PID" 2>/dev/null || true
  [[ -n "${GW_PID:-}" ]] && kill "$GW_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Fail fast if a target port is already bound. Otherwise a NEW server that
# fails to bind would leave the health probe talking to a pre-existing,
# unrelated server on that port — and the smoke would FALSELY pass. Ports are
# overridable (BRAIN_PORT / GW_PORT) if these collide with local dev.
port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
for p in "$BRAIN_PORT" "$GW_PORT"; do
  if port_in_use "$p"; then
    echo "FAIL: port $p is already in use — refusing to smoke-test against a foreign server (override BRAIN_PORT/GW_PORT)"
    exit 1
  fi
done

echo "→ starting Python brain"
( cd services/brain && BRAIN_BIND="$BRAIN_BIND" PYTHONPATH=src "$PYTHON" -m brain.server ) &
BRAIN_PID=$!

echo "→ starting Go gateway"
GATEWAY_ADDR="$GATEWAY_ADDR" BRAIN_ADDR="$BRAIN_ADDR" go run ./services/gateway &
GW_PID=$!

# Wait for gateway health — but bail the moment EITHER process we spawned dies,
# so a bind failure (or a crashed brain) is a hard FAIL, never a green health
# probe that happened to reach something else.
for i in $(seq 1 30); do
  kill -0 "$BRAIN_PID" 2>/dev/null || { echo "FAIL: brain process exited before serving"; exit 1; }
  kill -0 "$GW_PID" 2>/dev/null || { echo "FAIL: gateway process exited before serving (port bind failed?)"; exit 1; }
  if curl -sf http://localhost:${GW_PORT}/health >/dev/null 2>&1; then break; fi
  sleep 0.5
done

# Final guard in case the loop simply timed out: both must still be the LIVE
# processes we started, not a foreign server.
kill -0 "$BRAIN_PID" 2>/dev/null || { echo "FAIL: brain is not alive after health wait"; exit 1; }
kill -0 "$GW_PID" 2>/dev/null || { echo "FAIL: gateway is not alive after health wait"; exit 1; }

echo "→ gateway /health"
curl -sf http://localhost:${GW_PORT}/health && echo

echo "→ minting auth token (U18)"
TOKEN=$(GATEWAY_AUTH_SECRET="$GATEWAY_AUTH_SECRET" go run ./services/gateway -mint-token smoke user)

echo "→ gateway /valuation without token (expect 401)"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${GW_PORT}/valuation?address=x")
[[ "$code" == "401" ]] && echo "✓ unauthenticated request rejected (401)" || { echo "FAIL: expected 401, got $code"; exit 1; }

echo "→ gateway /valuation with token (round-trips to brain over gRPC)"
# The brain warms its AVM before serving; retry until it's ready.
RESP=""
for i in $(seq 1 30); do
  RESP=$(curl -sf -H "Authorization: Bearer $TOKEN" "http://localhost:${GW_PORT}/valuation?address=123%20Congress%20Ave%20Austin%20TX" 2>/dev/null) && \
    echo "$RESP" | grep -q '"sufficient_data":true' && break
  sleep 1
done
echo "$RESP"
echo "$RESP" | grep -q '"sufficient_data":true' || { echo "FAIL: no valuation"; exit 1; }
echo "✓ cross-language round-trip OK"
