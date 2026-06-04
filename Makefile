.PHONY: proto go-test brain-test rails-test test test-all smoke up down

# Per-language toolchains (override on the command line if yours differ):
#   PYTHON — a Python that has pytest + the brain deps (the stdlib python3 may not).
#   RAILS  — how to run the Rails suite; needs Ruby 3.3.11 (services/domain/.ruby-version) + `bundle install`.
PYTHON ?= python3
RAILS  ?= bin/rails test

proto:        ## Regenerate gRPC stubs from proto/ for all languages
	bash scripts/gen-proto.sh

go-test:      ## Go: build + vet + unit tests
	go build ./... && go vet ./... && go test ./...

brain-test:   ## Python brain unit tests (needs $(PYTHON) with pytest, e.g. PYTHON=/opt/anaconda3/bin/python3)
	cd services/brain && PYTHONPATH=src $(PYTHON) -m pytest -q

rails-test:   ## Rails domain unit tests (needs Ruby 3.3.11 via rbenv + `bundle install`)
	cd services/domain && $(RAILS)

test: go-test brain-test  ## Go + brain unit tests (run `make test-all` to include Rails)

test-all: go-test brain-test rails-test  ## Every suite: Go + Python brain + Rails domain

smoke:        ## Cross-language gRPC round-trip (gateway -> brain)
	bash scripts/smoke.sh

up:           ## Boot the full stack (Postgres+pgvector + services)
	docker compose up --build

down:
	docker compose down
