.PHONY: proto go-test brain-test test smoke up down

proto:        ## Regenerate gRPC stubs from proto/ for all languages
	bash scripts/gen-proto.sh

go-test:
	go build ./... && go vet ./... && go test ./...

brain-test:
	cd services/brain && python3 -m pytest -q

test: go-test brain-test  ## Run all unit tests

smoke:        ## Cross-language gRPC round-trip (gateway -> brain)
	bash scripts/smoke.sh

up:           ## Boot the full stack (Postgres+pgvector + services)
	docker compose up --build

down:
	docker compose down
