#!/usr/bin/env bash
# Generate gRPC stubs for every language from the shared proto contract.
# The proto/ contract is the single polyglot source of truth.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="/opt/homebrew/bin:$PATH:$(go env GOPATH)/bin"

PROTO_DIR=proto
PROTO_FILES=$(find "$PROTO_DIR" -name '*.proto')

echo "→ Go stubs"
mkdir -p proto/gen/go
protoc -I "$PROTO_DIR" \
  --go_out=proto/gen/go --go_opt=paths=source_relative \
  --go-grpc_out=proto/gen/go --go-grpc_opt=paths=source_relative \
  $PROTO_FILES

echo "→ Python stubs"
PY_OUT=services/brain/src/genproto
mkdir -p "$PY_OUT"
python3 -m grpc_tools.protoc -I "$PROTO_DIR" \
  --python_out="$PY_OUT" \
  --grpc_python_out="$PY_OUT" \
  $PROTO_FILES
# Make the generated tree an importable package and fix the absolute import
# grpc_tools emits (realestate.v1.x_pb2 -> genproto.realestate.v1.x_pb2).
find "$PY_OUT" -type d -exec touch {}/__init__.py \;
if [[ "$(uname)" == "Darwin" ]]; then SED=(sed -i ''); else SED=(sed -i); fi
find "$PY_OUT" -name '*_pb2_grpc.py' -exec "${SED[@]}" \
  -E 's/^from realestate/from genproto.realestate/' {} +

echo "✓ proto stubs generated"
