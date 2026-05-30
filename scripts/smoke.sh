#!/usr/bin/env bash
# U1 cross-language verification: start the Python Brain (gRPC) and call it
# through the Go gateway (REST -> gRPC), asserting the round-trip works.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:$PATH:$(go env GOPATH 2>/dev/null)/bin"

BRAIN_BIND="[::]:50051"
GATEWAY_ADDR=":8080"
BRAIN_ADDR="localhost:50051"

cleanup() {
  [[ -n "${BRAIN_PID:-}" ]] && kill "$BRAIN_PID" 2>/dev/null || true
  [[ -n "${GW_PID:-}" ]] && kill "$GW_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "→ starting Python brain"
( cd services/brain && BRAIN_BIND="$BRAIN_BIND" PYTHONPATH=src python3 -m brain.server ) &
BRAIN_PID=$!

echo "→ starting Go gateway"
GATEWAY_ADDR="$GATEWAY_ADDR" BRAIN_ADDR="$BRAIN_ADDR" go run ./services/gateway &
GW_PID=$!

# wait for gateway health
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then break; fi
  sleep 0.5
done

echo "→ gateway /health"
curl -sf http://localhost:8080/health && echo

echo "→ gateway /valuation (round-trips to brain over gRPC)"
RESP=$(curl -sf "http://localhost:8080/valuation?address=123%20Congress%20Ave%20Austin%20TX")
echo "$RESP"
echo "$RESP" | grep -q '"sufficient_data":true' || { echo "FAIL: no valuation"; exit 1; }
echo "✓ cross-language round-trip OK"
