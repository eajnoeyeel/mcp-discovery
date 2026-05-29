SHELL := /bin/bash
.DEFAULT_GOAL := build
ROOT := $(shell cd .. && pwd)

# All uv commands run from repo root where pyproject.toml lives
UV := cd $(ROOT) && uv run python -m

.PHONY: doctor lock build smoke local deploy clean help

help:  ## Show available targets
	@grep -E '^[a-z].*:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

doctor:  ## Pre-flight environment checks
	$(UV) service.build.doctor

lock:  ## Regenerate requirements.txt from pyproject.toml
	$(UV) service.build.lock

build: doctor  ## Build all Lambda artifacts into dist/
	$(UV) service.build.build

smoke:  ## Verify built artifacts (import + binary checks)
	$(UV) service.build.smoke

local: smoke  ## Start SAM local API (builds first if needed)
	$(UV) service.build.doctor -- --require-docker
	$(UV) service.build.local

deploy: smoke  ## Deploy to AWS via SAM
	cd $(ROOT)/service && sam deploy --no-confirm-changeset

clean:  ## Remove all build artifacts
	rm -rf dist/

