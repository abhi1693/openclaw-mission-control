.DEFAULT_GOAL := help

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-26s %s\n", $$1, $$2}'

.PHONY: setup
setup: backend-sync frontend-sync ## Install/sync backend + frontend deps

.PHONY: backend-sync
backend-sync: ## uv sync backend deps (includes dev extra)
	cd $(BACKEND_DIR) && uv sync --extra dev

.PHONY: frontend-sync
frontend-sync: ## npm install frontend deps
	cd $(FRONTEND_DIR) && npm install

.PHONY: format
format: backend-format frontend-format ## Format backend + frontend

.PHONY: backend-format
backend-format: ## Format backend (isort + black)
	cd $(BACKEND_DIR) && uv run isort .
	cd $(BACKEND_DIR) && uv run black .

.PHONY: frontend-format
frontend-format: ## Format frontend (prettier)
	cd $(FRONTEND_DIR) && npx prettier --write "src/**/*.{ts,tsx,js,jsx,json,css,md}" "*.{ts,js,json,md,mdx}"

.PHONY: format-check
format-check: backend-format-check frontend-format-check ## Check formatting (no changes)

.PHONY: backend-format-check
backend-format-check: ## Check backend formatting (isort + black)
	cd $(BACKEND_DIR) && uv run isort . --check-only --diff
	cd $(BACKEND_DIR) && uv run black . --check --diff

.PHONY: frontend-format-check
frontend-format-check: ## Check frontend formatting (prettier)
	cd $(FRONTEND_DIR) && npx prettier --check "src/**/*.{ts,tsx,js,jsx,json,css,md}" "*.{ts,js,json,md,mdx}"

.PHONY: lint
lint: backend-lint frontend-lint ## Lint backend + frontend

.PHONY: backend-lint
backend-lint: ## Lint backend (flake8)
	cd $(BACKEND_DIR) && uv run flake8 --config .flake8

.PHONY: frontend-lint
frontend-lint: ## Lint frontend (eslint)
	cd $(FRONTEND_DIR) && npm run lint

.PHONY: typecheck
typecheck: backend-typecheck frontend-typecheck ## Typecheck backend + frontend

.PHONY: backend-typecheck
backend-typecheck: ## Typecheck backend (mypy --strict)
	cd $(BACKEND_DIR) && uv run mypy

.PHONY: frontend-typecheck
frontend-typecheck: ## Typecheck frontend (tsc)
	cd $(FRONTEND_DIR) && npx tsc -p tsconfig.json --noEmit

.PHONY: test
test: backend-test ## Run tests

.PHONY: backend-test
backend-test: ## Backend tests (pytest)
	cd $(BACKEND_DIR) && uv run pytest

.PHONY: backend-migrate
backend-migrate: ## Apply backend DB migrations (alembic upgrade head)
	cd $(BACKEND_DIR) && uv run alembic upgrade head

.PHONY: build
build: frontend-build ## Build artifacts

.PHONY: frontend-build
frontend-build: ## Build frontend (next build)
	cd $(FRONTEND_DIR) && npm run build

.PHONY: api-gen
api-gen: ## Regenerate TS API client (requires backend running at 127.0.0.1:8000)
	cd $(FRONTEND_DIR) && npm run api:gen

.PHONY: backend-templates-sync
backend-templates-sync: ## Sync templates to existing gateway agents (usage: make backend-templates-sync GATEWAY_ID=<uuid> SYNC_ARGS="--reset-sessions")
	@if [ -z "$(GATEWAY_ID)" ]; then echo "GATEWAY_ID is required (uuid)"; exit 1; fi
	cd $(BACKEND_DIR) && uv run python scripts/sync_gateway_templates.py --gateway-id "$(GATEWAY_ID)" $(SYNC_ARGS)

.PHONY: check
check: lint typecheck test build ## Run lint + typecheck + tests + build
