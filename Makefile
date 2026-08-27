\
# Trellis workspace convenience targets.
#
# Thin wrappers around `uv run --package <name> ...` (see README.md "Getting
# started") — nothing here does anything `uv run` couldn't already do, this
# just saves typing the full invocation for the common cases. Anything not
# covered by a target still works via `make re CMD="..."` / `make ea CMD="..."`
# or the raw `uv run --package ...` form.

.DEFAULT_GOAL := help

RE_WEB_URL := http://localhost:8810
EA_WEB_URL := http://localhost:8880

.PHONY: help sync re re-web ea ea-web dev test test-re test-ea lint fmt prefect-up prefect-down

help: ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## /{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## uv sync the whole workspace
	uv sync

re: ## Run a resource-explorer CLI command: make re CMD="survey ..."
	uv run --package resource-explorer resource-explorer $(CMD)

re-web: ## Start Resource Explorer's web UI (http://localhost:8810)
	uv run --package resource-explorer resource-explorer web

ea: ## Run an egeria-advisor CLI command: make ea CMD="..."
	uv run --package egeria-advisor egeria-advisor $(CMD)

ea-web: ## Start Egeria Advisor's web UI (http://localhost:8880)
	uv run --package egeria-advisor egeria-advisor-web

dev: ## Start both web UIs concurrently; Ctrl-C stops both
	@echo "Resource Explorer -> $(RE_WEB_URL)"
	@echo "Egeria Advisor    -> $(EA_WEB_URL)"
	@trap 'kill 0' INT TERM; \
	( uv run --package resource-explorer resource-explorer web 2>&1 | sed -u 's/^/[RE] /' ) & \
	( uv run --package egeria-advisor egeria-advisor-web 2>&1 | sed -u 's/^/[EA] /' ) & \
	wait

test: test-re test-ea ## Run both test suites

test-re: ## Run resource-explorer's test suite
	uv run --package resource-explorer pytest packages/resource-explorer/tests

test-ea: ## Run egeria-advisor's test suite
	uv run --package egeria-advisor --extra dev pytest packages/egeria-advisor/tests

lint: ## ruff check both packages
	uv run --package resource-explorer ruff check packages/resource-explorer/resource_explorer
	uv run --package egeria-advisor ruff check packages/egeria-advisor/advisor

fmt: ## black both packages
	uv run --package resource-explorer black packages/resource-explorer/resource_explorer
	uv run --package egeria-advisor black packages/egeria-advisor/advisor

prefect-up: ## Bring up Prefect (server+worker) for RE's local survey-step dispatch — idempotent, bare-host only until Trellis is containerized (see the script)
	packages/resource-explorer/scripts/prefect_up.sh

prefect-down: ## Stop what prefect-up started
	packages/resource-explorer/scripts/prefect_down.sh
