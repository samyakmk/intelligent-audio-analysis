SHELL := /bin/sh
.DEFAULT_GOAL := help

PYTHON ?= python3.12
NPM ?= npm
CLIENT_DIR := apps/client
API_DIR := services/api
VENV_PYTHON := $(CURDIR)/$(API_DIR)/.venv/bin/python
API_PYTHON := $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(PYTHON))
SAFE_COMPOSE := $(PYTHON) scripts/compose.py

export EXPO_NO_DOTENV := 1

.PHONY: help setup run test test-backend test-client lint lint-backend lint-client \
	typecheck web export web-export prebuild fixtures migrate migration-current \
	migration-check compose-config compose-up compose-down compose-logs \
	compose-up-configured compose-config-configured

help: ## Show available commands.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install locked backend/client dependencies and verify fixtures.
	@sh scripts/setup.sh

run: ## Run the zero-account SQLite/filesystem API and Expo browser app.
	@$(PYTHON) scripts/run_local.py

fixtures: ## Verify generated media, sidecars, questions, and gate metadata.
	@$(PYTHON) scripts/generate_fixture_wav.py --check
	@$(PYTHON) scripts/verify_fixture_corpus.py
	@$(PYTHON) scripts/verify_env_example.py

test: fixtures test-backend test-client ## Run all deterministic tests.

test-backend: ## Run backend tests with fixture providers only.
	@cd $(API_DIR) && PROVIDER_MODE=fixture ALLOW_REMOTE_PROVIDER_CALLS=false \
		FIXTURE_ROOT=$(CURDIR)/fixtures $(API_PYTHON) -m pytest

test-client: ## Run client unit/component tests without dotenv loading.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) test

lint: lint-backend lint-client typecheck ## Run backend and client static checks.

lint-backend: ## Run Ruff over backend application and tests.
	@cd $(API_DIR) && $(API_PYTHON) -m ruff check app tests alembic

lint-client: ## Run the Expo ESLint configuration.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) run lint

typecheck: ## Type-check the universal TypeScript client.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) run typecheck

web: ## Start the Expo browser development server on port 8081.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) run web

export: ## Produce the static browser export in apps/client/dist.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) run export

web-export: export ## Alias for the static browser export.

prebuild: ## Generate clean iOS and Android native projects from shared source.
	@EXPO_NO_DOTENV=1 $(NPM) --prefix $(CLIENT_DIR) run prebuild -- --no-install

migrate: ## Upgrade DATABASE_URL (or the local SQLite default) to the schema head.
	@mkdir -p $(API_DIR)/data
	@cd $(API_DIR) && $(API_PYTHON) -m alembic upgrade head

migration-current: ## Show the migration revision applied to DATABASE_URL.
	@cd $(API_DIR) && $(API_PYTHON) -m alembic current

migration-check: ## Fail when the ORM metadata needs a new migration revision.
	@cd $(API_DIR) && $(API_PYTHON) -m alembic check

compose-config: ## Validate the safe-default Compose graph without reading .env.
	@$(SAFE_COMPOSE) config --quiet

compose-up: fixtures compose-config ## Build/start Postgres, MinIO, API, worker, and web with safe defaults.
	@$(SAFE_COMPOSE) up --build

compose-down: ## Stop safe-default Compose services; preserve named volumes.
	@$(SAFE_COMPOSE) down

compose-logs: ## Follow safe-default Compose logs.
	@$(SAFE_COMPOSE) logs --follow

compose-up-configured: ## Start with ENV_FILE=/explicit/path (never defaults to .env).
	@test -n "$(ENV_FILE)" || { echo "set ENV_FILE to an explicit configuration path" >&2; exit 2; }
	@$(PYTHON) scripts/compose.py --env-file "$(ENV_FILE)" up --build

compose-config-configured: ## Validate with ENV_FILE=/explicit/path.
	@test -n "$(ENV_FILE)" || { echo "set ENV_FILE to an explicit configuration path" >&2; exit 2; }
	@$(PYTHON) scripts/compose.py --env-file "$(ENV_FILE)" config --quiet
