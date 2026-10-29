.PHONY: help setup api web dev test lint fmt smoke synth api-types

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/'

setup: ## install backend + web dependencies
	cd backend && uv sync
	cd web && pnpm install

api: ## FastAPI on :8000 with reload; today pinned to the demo's date (TODAY=… to change)
	cd backend && TODAY=$(or $(TODAY),2026-11-05) uv run uvicorn kassenfest.api.app:app --reload --port 8000

web: ## Vite dev server on :5173 (proxies /api to :8000)
	cd web && pnpm dev

dev: ## API + web together
	$(MAKE) -j2 api web

test: ## backend unit tests (offline, no API key needed)
	cd backend && uv run pytest -q

lint: ## ruff + oxlint + typecheck
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd web && pnpm lint && pnpm typecheck

fmt: ## auto-format backend
	cd backend && uv run ruff format . && uv run ruff check --fix .

smoke: ## Muse Spark + SAM 3.1 end to end against the real API (MODE=replay needs no key)
	cd backend && uv run kassenfest smoke $(if $(MODE),--mode $(MODE),)

synth: ## synthetic set with ground truth: make synth SET=dev|test|demo (default dev)
	cd backend && uv run kassenfest synth --set $(or $(SET),dev)

api-types: ## regenerate web/src/api/schema.d.ts from the FastAPI models
	mkdir -p var
	cd backend && uv run python -c "import json; from kassenfest.api.app import app; print(json.dumps(app.openapi()))" > ../var/openapi.json
	cd web && pnpm gen:api
