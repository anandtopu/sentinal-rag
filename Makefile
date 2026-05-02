# SentinelRAG Makefile
# All commands assume the repo root as cwd.

.PHONY: help install up down restart logs ps seed clean \
        api retrieval ingestion evaluation worker frontend \
        lint fmt typecheck test test-unit test-int test-cov \
        db-revision db-upgrade db-downgrade \
        ollama-pull keycloak-bootstrap

# --- Help ---
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup ---
install: ## Install all dependencies (uv + pnpm). Installs every workspace member in editable mode so tests can import them.
	uv sync --all-packages
	cd apps/frontend && pnpm install || true

# --- Local stack ---
up: ## Start the full local docker-compose stack
	docker compose up -d
	@echo ""
	@echo "Stack starting. Wait ~30s for services to become healthy. Then:"
	@echo "  Postgres:    localhost:15432 (sentinel/sentinel; container is :5432)"
	@echo "  Redis:       localhost:6380  (host port; container is 6379)"
	@echo "  MinIO API:   http://localhost:9100  (minioadmin/minioadmin)"
	@echo "  MinIO UI:    http://localhost:9101  (minioadmin/minioadmin)"
	@echo "  Keycloak:    http://localhost:8080  (admin/admin)"
	@echo "  Temporal UI: http://localhost:8233"
	@echo "  Ollama:      http://localhost:11434"
	@echo "  Jaeger:      http://localhost:16686"
	@echo "  Prometheus:  http://localhost:9090"
	@echo "  Grafana:     http://localhost:3001  (admin/admin)"
	@echo "  Unleash:     http://localhost:4242  (admin/unleash4all)"

down: ## Stop the local stack (keep volumes)
	docker compose down

clean: ## Stop the local stack AND remove volumes (destroys all local data)
	docker compose down -v

restart: down up ## Restart the local stack

logs: ## Tail logs from all services
	docker compose logs -f

ps: ## List running stack containers
	docker compose ps

ollama-pull: ## Pre-pull Ollama models used by the platform
	docker compose exec ollama ollama pull llama3.1:8b
	docker compose exec ollama ollama pull nomic-embed-text

keycloak-bootstrap: ## Import the SentinelRAG realm into Keycloak (idempotent)
	docker compose restart keycloak
	@echo "Keycloak imports scripts/local/keycloak/realm-export.json on startup via --import-realm."

# --- App services (run locally with hot reload) ---
api: ## Run apps/api with hot reload
	uv run --package sentinelrag-api uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

retrieval: ## Run apps/retrieval-service with hot reload
	uv run --package sentinelrag-retrieval-service uvicorn sentinelrag_retrieval_service.main:app --reload --host 0.0.0.0 --port 8020

ingestion: ## Run apps/ingestion-service with hot reload
	uv run --package sentinelrag-ingestion-service uvicorn app.main:app --reload --host 0.0.0.0 --port 8030

evaluation: ## Run apps/evaluation-service with hot reload
	uv run --package sentinelrag-evaluation-service uvicorn sentinelrag_evaluation_service.main:app --reload --host 0.0.0.0 --port 8040

worker: ## Run Temporal worker
	uv run --package sentinelrag-temporal-worker python -m sentinelrag_worker.main

frontend: ## Run apps/frontend Next.js dev server
	cd apps/frontend && pnpm dev

# --- Quality ---
lint: ## Run ruff check + pyright across the workspace
	uv run ruff check .
	uv run pyright

fmt: ## Run ruff format
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Run pyright only
	uv run pyright

# --- Tests ---
test: test-unit ## Default test target — unit tests only

test-unit: ## Run unit tests
	uv run pytest -m unit

test-int: ## Run integration tests (uses testcontainers)
	uv run pytest -m integration

test-cov: ## Run all tests with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html

# --- Database ---
db-revision: ## Create a new alembic revision. Usage: make db-revision msg="add users table"
	@if [ -z "$(msg)" ]; then echo "ERROR: msg=... required"; exit 1; fi
	cd migrations && uv run alembic revision -m "$(msg)"

db-upgrade: ## Apply all pending migrations
	cd migrations && uv run alembic upgrade head

db-downgrade: ## Roll back one migration
	cd migrations && uv run alembic downgrade -1

# --- Seed ---
seed: ## Seed the local DB with a demo tenant + sample documents
	uv run python scripts/seed/seed_demo.py
