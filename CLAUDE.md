# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product

**SentinelRAG** — multi-tenant, RBAC-aware, evaluation-driven enterprise RAG platform. Full product spec in `Enterprise_RAG_PRD.md`. C4 diagrams in `Enterprise_RAG_Architecture.md`. DB schema + REST API contracts in `Enterprise_RAG_Database_Design.md`. Target monorepo layout in `Enterprise_RAG_Folder_Structure.md`. Terraform + K8s reference in `Enterprise_RAG_Deployment.md`.

The PRD/Architecture/Database/Deployment docs are **authoritative for product behavior, schema, API surface, and target topology** — but several stack-level decisions in those docs have been deliberately overridden during architecture review (see "Decision overrides" below). When the docs and the ADRs disagree, **the ADRs win**.

## Phase status

All 10 phases (0 → 9) are **code-side complete**; the only outstanding work
is the first deploy against a real cloud account and the live-traffic
artifacts that produces (drill-recorded RTOs, real eval/cost numbers,
5-min demo video). One-page summary at [`PROGRESS.md`](PROGRESS.md); the
live ledger is [`docs/architecture/PHASE_PLAN.md`](docs/architecture/PHASE_PLAN.md).
Always read both at the start of a session before doing planning or
implementation.

## Locked stack

| Layer | Choice | Reference |
|---|---|---|
| Language | Python 3.12 (services), TypeScript 5.x (frontend, SDK) | — |
| Backend framework | FastAPI + Pydantic v2 + SQLAlchemy 2.0 async + asyncpg | — |
| Migrations | Alembic, hand-written (no autogenerate) | — |
| Vector store | PostgreSQL 16 + pgvector with **HNSW** indexes | ADR-0003 |
| Keyword search v1 | **Postgres FTS + GIN on tsvector** behind `KeywordSearch` interface | ADR-0004 |
| Cache | Redis 7 | — |
| Object storage | S3 / GCS / MinIO local — raw text NOT stored in Postgres | ADR-0015 |
| LLM gateway | **LiteLLM** (unified routing + token accounting) | ADR-0005 |
| Default LLM (live demo) | Ollama Llama 3.1 8B; OpenAI/Anthropic via env-flag opt-in | ADR-0014 |
| Default embeddings | `nomic-embed-text` (Ollama) for self-hosted; `text-embedding-3-small` opt-in | ADR-0014 |
| Reranker | **bge-reranker-v2-m3** self-hosted; Cohere Rerank as adapter | ADR-0006 |
| Document parsing | `unstructured` library | ADR-0013 |
| Chunking strategies | semantic, sliding-window, structure-aware (per spec) | — |
| Async / workflow engine | **Temporal self-hosted** | ADR-0007 (overrides spec's Celery) |
| Auth | **Keycloak self-hosted** + OAuth2/JWT | ADR-0008 |
| Inter-service comms | **REST + Pydantic v2 contracts** in `packages/shared/python/contracts/` | ADR-0009 (overrides C4 L4 gRPC) |
| Hallucination detection | Layered: token-overlap → NLI (deberta) → LLM-as-judge sample | ADR-0010 |
| Audit log | Postgres + S3 with Object Lock (dual-write) | ADR-0016 |
| Feature flags | Unleash self-hosted | ADR-0018 |
| Eval framework | `ragas` + custom evaluators in `packages/shared/python/sentinelrag_shared/evaluation/` | ADR-0019 |
| Observability | OpenTelemetry SDK → OTel Collector → Tempo (traces) + Prometheus (metrics) + Loki (logs) | — |
| Logging | `structlog` JSON to stdout with trace correlation | — |
| Container registry | GHCR | — |
| K8s deployment | **Helm chart + ArgoCD GitOps** (no raw `kubectl apply` to prod) | ADR-0012 |
| Cloud scope | AWS primary (live), GCP mirror (verified deploy), Azure ADR-only | ADR-0011 |
| Frontend | Next.js 15 App Router + shadcn/ui + Tailwind + TanStack Query | ADR-0017 |
| Auth on frontend | NextAuth.js (Auth.js) bound to Keycloak | — |
| Tooling (Python) | **uv** workspace + **ruff** + **pyright** + pre-commit | ADR-0002 |
| Tooling (TS) | pnpm workspaces + biome (formatter+linter) + tsc strict | — |
| Testing | pytest + pytest-asyncio + testcontainers; vitest + playwright (frontend) | — |
| License | MIT | — |

## Decision overrides (where ADRs supersede the design docs)

The original design docs were drafted before architecture review. These overrides are intentional, recorded as ADRs, and should NOT be reverted to match the docs:

1. **`ivfflat` → HNSW** for pgvector (ADR-0003). Database Design doc Section 5.4 has the old index — migration must use HNSW.
2. **OpenSearch → Postgres FTS** for v1 (ADR-0004). All BM25 traffic goes through a `KeywordSearch` interface; OpenSearch is added in Phase 8 as a deliberate scale story behind the same interface. **Do not provision OpenSearch in early Terraform.**
3. **Celery → Temporal** for ingestion + evaluation pipelines (ADR-0007). The folder structure's `apps/api/app/workers/celery_app.py` is replaced by Temporal worker(s) in `apps/temporal-worker/` (or per-service workers). **Do not write Celery code.**
4. **gRPC → REST** between services (ADR-0009). C4 L4 mentions gRPC; ignore that.
5. **`raw_text TEXT` in `document_versions`** is moved out of Postgres into object storage (ADR-0015). The column is dropped or kept only for short docs (`<32 KB`); `storage_uri` is the source of truth.
6. **Hallucination detection** is layered, not single-shot LLM-as-judge (ADR-0010). LLM-as-judge runs only on flagged or sampled queries.
7. **Auth** is Keycloak self-hosted (ADR-0008), not Auth0/Clerk/Cognito. The user/role/permission tables in the schema remain the authoritative RBAC source — Keycloak is just the identity provider; we do NOT delegate role storage to Keycloak.

## Repo layout

Monorepo per `Enterprise_RAG_Folder_Structure.md`, with these adjustments:

- `apps/temporal-worker/` — Temporal workflow + activity workers; replaces Celery files in the spec.
- `apps/api/app/workers/` removed (Celery is gone).
- `infra/terraform/azure/` does NOT exist as code — only `docs/architecture/adr/0011-multi-cloud-strategy.md` describes the Azure mapping.
- `infra/terraform/aws/modules/opensearch/` exists (Phase 8 reintroduction per ADR-0026), but is intentionally **not wired into `environments/dev/main.tf`** — operators opt in via the steps in `docs/operations/runbooks/deployment-aws.md` if they want OpenSearch.
- `infra/bootstrap/` (Phase 7 Slice 3) — pinned values overlays + ArgoCD `Application` manifests for the upstream Helm charts (cert-manager, ALB controller, ESO + ClusterSecretStore, Temporal, ArgoCD, optional Chaos Mesh) the SentinelRAG chart depends on. Not bundled into the SentinelRAG chart per ADR-0030.
- `apps/api/` and other backend services share code via `packages/shared/python/` (logging, telemetry, auth, errors, contracts, retrieval, evaluation, audit, object_storage).

## Architecture pillars (do not violate)

These are enforced design rules. Violating them in a PR is a blocker:

1. **RBAC at retrieval time, not post-mask.** The `HybridRetriever` MUST receive an `AuthContext` and inject filter predicates into both BM25 and vector queries before candidates are fetched. Never filter results after retrieval.
2. **Tenant isolation via Postgres RLS.** Every request sets `app.current_tenant_id` at session start. RLS policies on every tenant-owned table enforce isolation as a defense-in-depth layer beneath app-level checks.
3. **Every answer is fully traceable.** A single `query_session_id` joins query → retrieval results (per stage) → generated answer → citations → eval scores → usage records. Never short-circuit this chain.
4. **Prompts are versioned artifacts.** Generation MUST resolve a `prompt_version_id` and persist it on `generated_answers`. No inline prompt strings in service code beyond defaults seeded at bootstrap.
5. **Cost is observed before it's optimized.** Every LLM call routes through the LiteLLM gateway; usage is double-entry recorded to `usage_records` with `query_session_id` linkage.
6. **Audit is immutable.** `audit_events` rows are append-only at app level AND mirrored to S3 with Object Lock. Never write a `DELETE` or `UPDATE` against `audit_events`.

## Working notes for future Claude instances

- **Read the current ADR catalog first.** `docs/architecture/adr/README.md` has the index. ADRs are the source of truth for "why is it like this."
- **Prefer extending the contracts package over duplicating types.** Pydantic models for cross-service messages live in `packages/shared/python/contracts/`.
- **Each service has its own pyproject.toml** under the uv workspace at the root. To add a dep to one service: `uv add <pkg> --package sentinelrag-api`.
- **Local dev:** `make up` brings up the full stack via docker-compose (Postgres, Redis, MinIO, Keycloak, Temporal, Ollama, observability). `make seed` populates a demo tenant.
- **Tests against real infra:** integration tests use `testcontainers-python` to spin up Postgres+pgvector. Do NOT mock the database in retrieval/RBAC tests — RLS bugs only surface against a real Postgres.
- **Migrations:** every schema change is a hand-written Alembic revision. `make db-revision msg="..."`. Never `alembic revision --autogenerate`.
- **Sensitive defaults:** `text-embedding-3-small` produces 1536-dim vectors; `nomic-embed-text` produces 768-dim. The `chunk_embeddings` table has `embedding_model TEXT` + per-model rows precisely so we can run both. **Do not change the column to a fixed dim.**
- **Multi-cloud parity:** Helm chart is the single deployment artifact. Terraform differs per cloud, but the K8s manifests must be identical AWS↔GCP. If you find yourself writing cloud-specific K8s, it belongs in a Helm value override, not a fork.
- **Deployment is documented end-to-end.** When a session involves "deploy to AWS / GCP" follow `docs/operations/runbooks/deployment-{aws,gcp}.md` and the shared `cluster-bootstrap.md`. Do not re-derive the procedure from scratch.
- **Feature testing has its own runbook.** When verifying that a code change preserves a documented feature (RBAC at retrieval time, audit immutability, cost gate, etc.), use `docs/operations/runbooks/testing-guide.md` as the canonical matrix.

## Local dev: skipping Keycloak

For local smoke tests + integration tests we ship a **dev-token bypass** in `app/core/auth.py`. It's gated by **two** flags that must both be set: `ENVIRONMENT=local` AND `AUTH_ALLOW_DEV_TOKEN=true`. Both default to `False` outside `.env`. With them enabled, calling any authenticated route with `Authorization: Bearer dev` returns a synthesized AuthContext for the seeded demo tenant + admin user (provisioned by `make seed`).

This is the path used by integration tests and the local upload smoke test. **Never enable in dev/staging/prod** — Pydantic settings + the `environment != local` guard make this hard to do by accident, but the rule is tested in `tests/unit/test_dev_token_disabled_in_prod.py`.

## Common commands

```bash
make up           # docker-compose up -d (full local stack)
make down         # docker-compose down -v
make seed         # populate demo tenant + sample documents
make api          # run apps/api locally with hot reload
make worker       # run Temporal worker (apps/temporal-worker)
make frontend     # run apps/frontend Next.js dev server
make test         # run all Python tests (alias for test-unit)
make test-unit    # run unit tests only
make test-int     # integration tests with testcontainers
make lint         # ruff + pyright across the workspace
make fmt          # ruff format
make db-revision msg="..."   # new alembic revision
make db-upgrade   # apply migrations
```

Per-feature smoke and verification commands live in
`docs/operations/runbooks/testing-guide.md`. Deployment commands are in
`docs/operations/runbooks/deployment-{aws,gcp}.md`. When this list and a
runbook disagree, the runbook is canonical.

## Things NOT to do (recurring footguns)

- Don't mock the DB in tests that exercise RLS, tenancy, or RBAC retrieval — the bug surface is in the real Postgres behavior.
- Don't store raw document text or large extracted text in Postgres — push to object storage, keep `storage_uri`.
- Don't write Celery code. Temporal workflows + activities only.
- Don't enable OpenSearch by default. The `KeywordSearch` adapter exists (ADR-0026) but Postgres FTS is the always-on default; OpenSearch is feature-flagged via Unleash and gated by an opt-in step in the AWS deployment runbook. Don't make queries fan out to both backends — pick one per request via the flag.
- Don't put inline prompt strings in service code outside of seeded defaults — go through `prompt_service`.
- Don't add cloud-specific code to the K8s manifests. Use Helm values overrides.
- Don't bundle bootstrap charts (cert-manager, ESO, Temporal, ArgoCD) into the SentinelRAG chart. They live at `infra/bootstrap/` per ADR-0030 — different lifecycle, different artifact.
- Don't create `*.md` documentation outside `docs/`, `infra/`, and `*ADR*.md` files unless the user asks. Top-level `PROGRESS.md` and `README.md` are intentional exceptions.
- Don't add backwards-compat shims, removed-code comments, or rename-unused-vars sweeps. Just delete.
- Don't trust an embedding `vector` column's hardcoded dimension when introducing new models — write a migration that adds a per-model row, don't ALTER the column.
- Don't write static eval / cost numbers into the report markdowns. The harnesses at `tests/performance/evals/compare.py` + `scripts/cost/render_report.py` overwrite those files on every run; numbers committed by hand will get clobbered and risk being read as real when they aren't (ADR-0029).
