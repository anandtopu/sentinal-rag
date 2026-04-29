# Local development runbook

The README quick-start gets you to a running API and a populated demo
tenant. This runbook covers everything beyond that:

- Per-service hot reload (api / temporal-worker / frontend)
- Common troubleshooting (Redis port collision, Ollama warm-up, Keycloak
  realm import, JWKS cache, stale frontend deps)
- Running integration tests against testcontainers
- Working with the database (migrations, RLS, demo data reset)
- Working with Temporal (task queues, workflow inspection, retries)
- Adding a new dependency (workspace-aware)

When this runbook contradicts CLAUDE.md or the README quick-start, **the
runbook wins** — it's the canonical local-dev procedure.

---

## Stack components, ports, and credentials

`make up` brings up the full local stack via `docker-compose.yml`. Each
component is reachable from the host at:

| Component | Host URL | Default credentials |
|---|---|---|
| Postgres + pgvector | `localhost:15432` | `sentinel` / `sentinel`, db `sentinelrag` |
| Redis | `localhost:6380` | no auth (local only) |
| MinIO API | `http://localhost:9100` | `minioadmin` / `minioadmin` |
| MinIO console | `http://localhost:9101` | `minioadmin` / `minioadmin` |
| Keycloak | `http://localhost:8080` | `admin` / `admin` |
| Temporal frontend | `localhost:7233` (gRPC) | no auth (local only) |
| Temporal Web UI | `http://localhost:8233` | no auth |
| Ollama | `http://localhost:11434` | no auth |
| Jaeger UI | `http://localhost:16686` | no auth |
| Prometheus | `http://localhost:9090` | no auth |
| Grafana | `http://localhost:3001` | `admin` / `admin` |
| Unleash | `http://localhost:4242` | `admin` / `unleash4all` |

Postgres is mapped to host port **15432** (container is 5432) and Redis
to **6380** (container is 6379) so both work even when you have a native
Postgres or Redis running on standard ports. This is documented in the
docker-compose file and ADR-0001's accompanying memory.

## First-time setup

```bash
# 1. uv (Python). One-time install.
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Resolve the workspace.
uv sync --all-packages

# 3. (Optional) Frontend deps.
cd apps/frontend && npm install && cd ../..

# 4. Pull Ollama models. ~5 GB; one-time.
make up
make ollama-pull

# 5. Run migrations + seed.
make db-upgrade
make seed
```

`make seed` creates:
- A demo tenant: `demo-tenant`, ID `00000000-0000-0000-0000-000000000001`.
- A demo admin user: `demo-admin@sentinelrag.example.com`,
  ID `00000000-0000-0000-0000-000000000010`.
- One demo collection with sample documents (3-5 PDFs from `tests/fixtures/`).
- A default prompt template.

## Per-service hot reload

Each backend service runs in a dedicated terminal. None of them are
managed by docker-compose (the API container in compose is for smoke
tests; you run the live one yourself).

### API
```bash
make api
# Or:
uv run --package sentinelrag-api uvicorn app.main:app --reload \
  --host 0.0.0.0 --port 8000
```

The dev token bypass is gated by **two** flags. To enable for local smoke
testing, in `apps/api/.env`:
```
ENVIRONMENT=local
AUTH_ALLOW_DEV_TOKEN=true
```
Then:
```bash
curl -H "Authorization: Bearer dev" http://localhost:8000/api/v1/health
```

### Temporal worker
```bash
make worker
# Or:
uv run --package sentinelrag-temporal-worker python -m sentinelrag_worker.main
```

The worker registers three task queues: `ingestion`, `evaluation`, and
`audit`. The first activity invocation pre-warms the tiktoken encoding
(~3 s); subsequent activities are fast.

### Frontend
```bash
make frontend
# Or:
cd apps/frontend && npm run dev
```

Next.js dev mode rewrites `/api/*` to `http://localhost:8000/api/v1/*`
(see `apps/frontend/next.config.mjs`). Production builds skip the
rewrite — Ingress routes API calls in deployed environments.

To use the dev-token bypass from the frontend without minting a Keycloak
token, set in `apps/frontend/.env.local`:
```
AUTH_DEV_BYPASS=true
```
This activates a `Credentials` provider in `lib/auth.ts`.

## Common troubleshooting

### Redis port conflict — "Address already in use"

A native Redis on host port 6379 conflicts with the docker-compose Redis.
We map to host port **6380** by default; if you still see the conflict,
something else has grabbed 6380. Find + stop it:
```bash
lsof -i :6380          # macOS / Linux
ss -tlnp | grep 6380   # Linux
```

### Ollama returns 404 on first query

Models aren't pulled until you ask. `make up` does NOT auto-pull (the
download is multi-GB). Run `make ollama-pull` once after `make up` and
wait for both `llama3.1:8b` and `nomic-embed-text` to finish.

To verify:
```bash
docker compose exec ollama ollama list
```

### Keycloak realm import

`make up` brings Keycloak online but does NOT import the SentinelRAG
realm. Two options:

1. **Skip Keycloak entirely (recommended for unit work).** Set
   `AUTH_ALLOW_DEV_TOKEN=true` and use `Authorization: Bearer dev`.
2. **Import the realm.** `make keycloak-bootstrap` (currently a TODO
   stub — Phase 9 polish item). Manual import:
   ```bash
   docker compose exec keycloak \
     /opt/keycloak/bin/kc.sh import \
     --file /opt/keycloak/data/import/sentinelrag-realm.json
   ```
   (The realm JSON ships at `scripts/local/keycloak/sentinelrag-realm.json`.)

### JWKS cache returns stale keys after Keycloak restart

The API caches JWKS for 10 minutes by default. After `docker compose restart
keycloak`, restart the API too — or wait out the cache TTL.

### Frontend showing "Failed to fetch" on every API call

1. Check the API is up: `curl http://localhost:8000/api/v1/health`.
2. Check `NEXT_PUBLIC_API_URL` in `apps/frontend/.env.local`. Default
   is `http://localhost:8000` (without `/api/v1`).
3. CORS — the API accepts `http://localhost:3000` by default; if you're
   on a non-default port, set `CORS_ALLOWED_ORIGINS` in the API env.

### `make seed` says "tenant already exists"

`make seed` is **not idempotent** today (Phase 9 polish leftover). To re-seed
fresh, blow away volumes:
```bash
make clean   # docker compose down -v — destroys all local data
make up
make db-upgrade
make seed
```

### Pyright reports ~150 errors in strict mode

Documented in PHASE_PLAN.md as the typecheck baseline. Don't fix in a
single sweep; tighten incrementally as you touch each module. Don't
let the baseline grow.

### `uv sync` fails with a 403 from PyPI

`uv` respects `UV_INDEX_URL` and proxy env vars. If you're on a corp
network, set:
```bash
export UV_INDEX_URL=<your mirror>
export UV_HTTP_TIMEOUT=300
```

### `helm template` errors with "missing in charts/ directory"

Helm 4 expects extracted dependency directories, not `.tgz` tarballs.
After `helm dependency build`, extract:
```bash
cd infra/helm/sentinelrag/charts
for f in *.tgz; do tar -xzf "$f"; done
```
This is documented at the top of the AWS deploy runbook too.

## Running tests

```bash
# Unit — fast, no infra.
uv run pytest -m unit

# Integration — testcontainers will spin up a Postgres+pgvector pod.
# REQUIRES Docker Desktop running; takes 30-60 s for first run.
uv run pytest -m integration

# Just one test file.
uv run pytest apps/api/tests/unit/test_jwt_verifier.py -v

# Frontend.
cd apps/frontend && npm run test                # vitest unit
cd apps/frontend && npm run test:e2e            # Playwright e2e
```

The integration suite uses testcontainers; it spins up Postgres+pgvector
for each test class to give RLS bugs nowhere to hide. Don't try to mock
your way around it — see CLAUDE.md "Things NOT to do."

## Database workflow

### Adding a migration

```bash
make db-revision msg="add foo table"
# Creates migrations/versions/<timestamp>_add_foo_table.py — hand-edit it.
# DO NOT use --autogenerate.
```

Every migration that creates a tenant-owned table must also enable RLS:
```python
op.execute("ALTER TABLE foo ENABLE ROW LEVEL SECURITY")
op.execute("""
    CREATE POLICY tenant_isolation ON foo
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
""")
```

Then:
```bash
make db-upgrade
# Smoke: connect, set the GUC, query.
docker compose exec postgres psql -U sentinel sentinelrag
> SET LOCAL app.current_tenant_id = '00000000-0000-0000-0000-000000000001';
> SELECT * FROM foo;     -- should only see tenant 1's rows
```

### Resetting demo data

```bash
make clean
make up
make db-upgrade
make seed
```

This nukes everything — only do it on local.

### Inspecting RLS

```bash
docker compose exec postgres psql -U sentinel sentinelrag -c "\d collections"
# Look for: "Policies: tenant_isolation"
```

## Temporal workflow

### Inspecting workflows

`http://localhost:8233` — Temporal Web UI. Lists every workflow run
(ingestion, evaluation, audit-reconciliation), with full history.

### Forcing a re-run

Workflows are idempotent (Temporal at-least-once + idempotent activity
design). To re-trigger an ingestion for a specific document:
```bash
docker compose exec temporal-admin-tools tctl workflow start \
  --task-queue ingestion \
  --workflow-type IngestionWorkflow \
  --input '{"document_id": "<uuid>", ...}'
```

### Stuck workflows

If a workflow shows as `Running` for >10 min, check the worker logs:
```bash
docker compose logs -f temporal-worker
```

A common stall is `tiktoken` failing to load on first activity (network
hiccup downloading the BPE). Worker auto-retries; the workflow will
catch up on the next attempt.

## Adding a workspace dependency

The repo is a uv workspace. To add a Python dependency to a single
package:
```bash
uv add <pkg> --package sentinelrag-api
```

To add it to the shared lib (visible to every service):
```bash
uv add <pkg> --package sentinelrag-shared
```

Then commit `uv.lock` so CI sees the resolution.

For frontend dependencies:
```bash
cd apps/frontend && npm install <pkg>
```

## Useful one-liners

```bash
# Tail every container.
docker compose logs -f

# Show every running pod's status.
docker compose ps

# Reset just Redis.
docker compose restart redis

# Drop into the API venv for a one-off.
uv run --package sentinelrag-api python -c "from app.core.config import get_settings; print(get_settings())"

# List Temporal task queues this worker handles.
docker compose exec temporal-admin-tools tctl taskqueue list-partition --task-queue ingestion

# Re-render the Helm chart and look at one workload.
cd infra/helm/sentinelrag
helm template release-test . -f values-local.yaml | yq 'select(.kind == "Deployment" and .metadata.name | contains("api"))'
```

## Cross-references

- [`testing-guide.md`](testing-guide.md) — feature-by-feature verification matrix
- [`deployment-aws.md`](deployment-aws.md) / [`deployment-gcp.md`](deployment-gcp.md) — getting to a real cluster after local works
- [`disaster-recovery.md`](disaster-recovery.md) — recovery once you're deployed
- [`CLAUDE.md`](../../../CLAUDE.md) — architectural pillars, footguns, "things NOT to do"
- [`README.md`](../../../README.md) — repo tour + quick-start
