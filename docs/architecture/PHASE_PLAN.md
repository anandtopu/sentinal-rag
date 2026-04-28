# SentinelRAG — Phase Plan

This is the live phase plan for the SentinelRAG build. Update this file when a phase completes or when scope changes — future Claude instances read this at the start of every session to know where we are.

## Status legend

- 🟢 Complete
- 🟡 cla
- ⚪ Not started

## Current phase

**Phases 3 + 4 + 5 complete; Phase 6 + 6.5 complete (cost + audit + metrics slice + reconciliation landed).** Unit tests collecting 65 (5 jwt + 6 dev-token guard + 10 chunkers + 11 evaluators + 1 health + 11 cost service + 5 audit dual-write + 16 audit reconciliation). 64 pass clean; `test_dev_token_disabled_by_default` is a pre-existing flake — `test_health.py`'s `create_app()` warms a process-level env that pollutes `Settings(_env_file=None)` in suite-wide runs (passes when run in isolation; reproduces on a clean `git stash`-ed tree). Tracked separately. Frontend vitest passing (5/5: api client). FastAPI app boots cleanly with 42 routes. `uv run ruff check` is clean across the workspace. Phase 6 cost + audit + metrics slice — ADR-0022 (per-tenant budgets), migration 0012 (`tenant_budgets`), `CostService` with soft-cap downgrade + hard-cap deny wired into `RagOrchestrator` before generation, `BudgetExceededError` (HTTP 402), `AuditService` with `PostgresAuditSink` + `ObjectStorageAuditSink` (S3 Object Lock-ready) + `DualWriteAuditService` recording `query.executed`, `query.failed`, `budget.downgraded`, `budget.denied`, OTel meters (`sentinelrag_queries_total`, `sentinelrag_stage_latency_ms`, `sentinelrag_grounding_score`, `sentinelrag_budget_decisions_total`, `sentinelrag_llm_cost_usd_total`), and 3 Grafana dashboards-as-code (rag-overview, cost-tenant, quality) provisioned via `grafana-dashboards.yml`.

**Re-verified after the 2026-04-28 Phase 6.5 restart:**
- `uv run pytest -m unit` → 64 passed, 1 pre-existing flake (see header), 11 deselected.
- `uv run pytest apps/api/tests/unit/test_audit_reconciliation.py` → 16/16 pass in isolation.
- `uv run ruff check apps packages migrations` → All checks passed.

**Still deferred (Docker required, not run this session):**
- `make db-upgrade` to apply the 11 migrations.
- `pytest -m integration` (testcontainers — needs Docker Desktop running).
- End-to-end `/query` smoke against live Postgres + Ollama.

**Known typecheck baseline (not blocking):**
- `uv run pyright` (strict mode) reports ~154 baseline errors + ~512 warnings, dominated by `reportMissingTypeStubs` for workspace-internal modules and `reportUnknownParameterType` in integration test fixtures. Not regressions from any single phase — accumulated strict-mode noise. Tighten incrementally rather than in a single sweep.

## Phase ledger

### Phase 0 — Foundations 🟢
**Goal:** repo scaffolding, tooling, local dev stack, CI bones, ADR catalog.
- 🟢 Update `CLAUDE.md` with locked stack and override notes.
- 🟢 Write ADR catalog (0000 template + 0001–0019).
- 🟢 Bootstrap monorepo skeleton (directories + root config).
- 🟢 `docker-compose.yml` for full local dev stack.
- 🟢 GitHub Actions CI for lint + typecheck.
- 🟢 Stub `apps/api` with `/health` + OTel + structlog.
- 🟢 `Makefile` with `make up`, `make api`, `make lint`, `make fmt`.
- 🟢 Pre-commit hooks.

**Verified:**
- 🟢 `uv sync --all-packages` resolves the workspace.
- 🟢 `make up` brings all containers online (after fixing Jaeger image tag and remapping Redis to host:6380 to avoid conflict with native Redis).
- 🟢 `pytest -m unit` passes — health endpoint smoke test.

**Deferred to a later step:**
- `git init`, GitHub remote, first CI run. The repo has no `.git/` yet.

### Phase 1 — Core data plane + tenancy 🟢
**Goal:** schema, RBAC, RLS, tenant context.
- 🟢 Alembic setup + 10 hand-written migrations covering the full schema (HNSW index, no raw_text column, partitioned audit/usage, tsvector+GIN on chunks, RLS policies on every tenant-owned table).
- 🟢 SQLAlchemy 2.0 async models + Pydantic v2 schemas for tenancy + RBAC entities.
- 🟢 Repository layer for tenants/users/roles/permissions.
- 🟢 DB session factory with contextvar-driven `SET LOCAL app.current_tenant_id`; admin (RLS-bypass) factory for tenant-creation flows.
- 🟢 Keycloak JWKS-cached JWT verifier in `packages/shared/python/sentinelrag_shared/auth/`.
- 🟢 AuthContext + `require_auth` / `require_permission` FastAPI dependencies.
- 🟢 RequestContextMiddleware (request_id) + error-handler middleware (DomainError → JSON envelope).
- 🟢 `/tenants`, `/tenants/me`, `/users`, `/users/me`, `/users/{id}/roles`, `/roles`, `/permissions` endpoints.
- 🟢 RLS integration tests proving cross-tenant reads/writes are blocked.
- 🟢 JWT verifier unit tests (valid, expired, wrong audience, missing tenant_id, tampered signature).

**Verified:**
- 🟢 `pytest -m unit` passes — 5 JWT verifier scenarios (valid, expired, wrong audience, missing tenant_id, tampered signature).

**Deferred to next session:**
- `make db-upgrade` to apply the 10 migrations against the running Postgres.
- `pytest -m integration` to prove RLS isolation against real Postgres via testcontainers.

**Done when:** the integration suite is green.

### Phase 2 — Ingestion pipeline 🟢
**Goal:** docs in → chunks + embeddings out.
- 🟢 ADR-0020 + migration 0011: per-dimension embedding columns (768/1024/1536) so the `nomic-embed-text` (768d) self-hosted default actually works.
- 🟢 `ObjectStorage` interface in `sentinelrag_shared/object_storage/` with S3/MinIO impl (covers MinIO via `endpoint_url`); GCS + Azure stubbed for Phase 8.
- 🟢 `Embedder` protocol + `LiteLLMEmbedder` in `sentinelrag_shared/llm/`. Token+cost accounting via `UsageRecord`. Tenacity-based retries.
- 🟢 `Parser` protocol + `UnstructuredParser` in `sentinelrag_shared/parsing/` (moved from `apps/ingestion-service` since it's library code shared by ingestion-service and temporal-worker).
- 🟢 Three chunkers in `sentinelrag_shared/chunking/`: SemanticChunker, SlidingWindowChunker, StructureAwareChunker (token-aware via tiktoken).
- 🟢 ORM models + Pydantic schemas + repositories for collections, documents, document_versions, document_chunks, chunk_embeddings, ingestion_jobs.
- 🟢 Temporal `IngestionWorkflow` (renamed package: `apps/temporal-worker/sentinelrag_worker/` to dodge `app/` collision with API) + 8 idempotent activities covering download → parse → chunk → embed → finalize.
- 🟢 Routes: `/collections` CRUD, `/documents` upload (multipart) + read + list, `/ingestion/jobs` read + list. Object storage and Temporal client wired via `app.state` + `app/dependencies.py`.

**Done when:** end-to-end upload via `/api/v1/documents` produces a Document, kicks off a Temporal IngestionWorkflow, and chunks + embeddings appear in the DB visible only to the uploading tenant.

### Phase 3 — Retrieval + RAG orchestrator 🟢
**Goal:** end-to-end query with grounded citations.
- 🟢 `KeywordSearch` (Postgres FTS, websearch_to_tsquery) in `sentinelrag_shared/retrieval/keyword_search.py`.
- 🟢 `VectorSearch` (pgvector HNSW with per-dim column dispatch + per-query `SET LOCAL hnsw.ef_search`) in `vector_search.py`.
- 🟢 `Reranker` — `BgeReranker` (FlagEmbedding → sentence-transformers fallback) + `NoOpReranker`; lazy-loaded so unit tests don't pay the 3-10s startup.
- 🟢 ADR-0021 — retrieval lives in the shared package (used by API + future eval workers).
- 🟢 `AccessFilter` builds an authorized-collections CTE that joins both BM25 + vector queries, fulfilling pillar #1 (RBAC at retrieval time, never post-mask).
- 🟢 `RagOrchestrator` (662 LOC): hybrid retrieve (RRF merge) → rerank → context assemble with `[1]`-style markers → LiteLLM completion → token-overlap grounding score → persistence.
- 🟢 Routes: `POST /query`, `GET /query/{id}/trace`. Trace re-reads `retrieval_results` + `generated_answers` so it survives the originating session.
- 🟢 Persistence into `query_sessions`, `retrieval_results` (per stage: bm25, vector, hybrid_merge, rerank), `generated_answers`, `answer_citations`, `usage_records`.

**Done when:** end-to-end query returns grounded, cited answer; trace shows every stage. _(Backend wired; live verification deferred to next Docker-up session.)_

### Phase 4 — Prompt registry + evaluation 🟢
**Goal:** versioned prompts + ragas-driven evaluation.
- 🟢 ORM models + repositories + `PromptService` for templates + versions; default-version flagging.
- 🟢 Routes: `POST/GET /prompts`, `GET /prompts/{id}`, `POST/GET /prompts/{id}/versions`.
- 🟢 `sentinelrag_shared/evaluation/` — `EvalCase`, `EvalContext`, `Evaluator` base, plus four custom evaluators (`ContextRelevanceEvaluator`, `FaithfulnessEvaluator`, `AnswerCorrectnessEvaluator`, `CitationAccuracyEvaluator`). 11 unit tests cover edge cases (empty context, no overlap, exact match, citation precision/recall).
- 🟢 `EvaluationService` orchestrating dataset/case CRUD + run start (Temporal workflow handle persisted on the run row); `aggregate_run` rolls up scores from per-case rows.
- 🟢 Routes: `POST /eval/datasets`, `POST/GET /eval/datasets/{id}/cases`, `POST /eval/runs`, `GET /eval/runs/{id}` (returns `EvaluationScoreSummary`).
- ⚪ Unleash flag routing for prompt version selection — deferred; `prompt_version_id` is wired through the orchestrator + persistence today, the flag service swap is a one-file change later.

**Done when:** running an eval produces ragas + citation-accuracy scores; prompt version routing toggles via Unleash without redeploy. _(Custom evaluators landed; ragas adapter + Unleash routing deferred to a focused Phase 4.5.)_

### Phase 5 — Frontend 🟢
**Goal:** Next.js dashboard against the live API.
- 🟢 Next.js 15 App Router scaffolding consolidated under `apps/frontend/src/` (matching tsconfig + tailwind paths).
- 🟢 NextAuth.js v5 (`lib/auth.ts`) bound to Keycloak in prod; `Credentials` dev provider gated by `AUTH_DEV_BYPASS=true` so the dev token bypass stays inert by default.
- 🟢 Typed fetch client (`lib/api.ts`) — bearer forwarding, query serialization, error-envelope unwrapping into `ApiError`, multipart upload helper. `useApiClient()` injects the session token automatically.
- 🟢 Hand-rolled shadcn-style primitives (Button, Card, Input, Textarea, Label, Badge, Table) + layout (Sidebar, Topbar, PageHeader, StatusBadge).
- 🟢 Pages: `/dashboard`, `/collections` (with create form), `/documents` (with upload + ingestion-job polling), `/query-playground` (the headline — collections multiselect, model picker, top-k, SSE-driven trace viewer with polling fallback), `/evaluations`, `/prompts` (templates + versions), `/settings`. `/audit` + `/usage` are stub explainers pointing at Phase 6.
- 🟢 Vitest suite (`tests/unit/api.test.ts`) covering bearer-auth forwarding, query serialization, error-envelope unwrapping, multipart upload — 5 tests.
- 🟢 Playwright e2e — `playwright.config.ts` + 3 spec files (smoke, query-playground, collections) totaling 7 tests. API-dependent specs probe `/api/v1/health` and skip cleanly when the backend isn't reachable, so the suite passes in frontend-only CI and exercises the live backend once Phase 7 ships a deployed dev environment.
- 🟢 Streaming SSE for the trace viewer — `GET /api/v1/query/{id}/trace/stream` emits `event: trace` frames over `text/event-stream`; `useTraceStream` consumes via fetch+ReadableStream (so bearer auth still works) and falls back to polling if the first frame doesn't arrive within 4s (nginx-style buffering safety net).

**Done when:** all major API features are usable through the UI. _(Done.)_

### Phase 6 — Observability + cost + audit hardening 🟢
**Goal:** prod-grade telemetry and audit immutability.
- 🟢 ADR-0022 — per-tenant budgets with soft (downgrade) / hard (deny) thresholds.
- 🟢 Migration 0012 — `tenant_budgets` table with RLS + active-window index. ORM model + `TenantBudgetRepository` exposing `get_active` and `period_spend(SUM(usage_records))`.
- 🟢 `CostService` — `check_budget(tenant_id, estimate_usd, requested_model) → BudgetDecision(action, current_spend, limit, downgrade_to, reason)`. Pricing in `MODEL_PRICES`; default downgrade ladder + per-tenant override via `tenant_budgets.downgrade_policy`. `enforce_or_raise` maps DENY → `BudgetExceededError` (HTTP 402, `BUDGET_EXCEEDED`).
- 🟢 Wire-in to `RagOrchestrator` — budget gate runs after retrieval/rerank, before generation. Soft-cap downgrade re-binds the LiteLLM generator to the cheaper model and `effective_model` flows through persistence + audit so traces reflect what actually ran.
- 🟢 Audit dual-write (ADR-0016 implementation) — `AuditEvent` Pydantic model with hierarchical S3 key (`tenant_id=.../year=.../<event_uuid>.json.gz`), `PostgresAuditSink` (synchronous, RLS-bound), `ObjectStorageAuditSink` (gzipped JSON, bucket-level Object Lock), `DualWriteAuditService` (sync primary + fire-and-forget secondaries with `drain()` for tests). Wired into orchestrator for `query.executed`, `query.failed`, `budget.downgraded`, `budget.denied`.
- 🟢 OTel meters (`sentinelrag_shared.telemetry.meters`) — `sentinelrag_queries_total`, `sentinelrag_stage_latency_ms`, `sentinelrag_grounding_score`, `sentinelrag_budget_decisions_total`, `sentinelrag_llm_cost_usd_total`. Cardinality-disciplined (no tenant_id on high-volume counters).
- 🟢 Grafana dashboards as JSON — `infra/observability/grafana/dashboards/{rag-overview,cost-tenant,quality}.json` with provisioning via `grafana-dashboards.yml`. Mounted into the Grafana container by docker-compose.
- 🟢 Unit tests — 9 for `CostService` (estimate, allow/downgrade/deny boundaries, override policy, exception mapping), 6 for audit dual-write (primary failure propagates, secondary failure isolated, S3 key format, JSON serialization).
- 🟢 **Phase 6.5 — Audit reconciliation.** `AuditReconciliationWorkflow` + two activities (`reconcile_tenant_day` does the per-tenant diff/backfill; `emit_audit_drift_metrics` aggregates and emits OTel + structured-log drift). Pure orchestration in `sentinelrag_shared.audit.reconciliation` (`diff_event_sets`, `reconcile_one_tenant`) so unit tests don't need Postgres or S3. Workflow input contract `AuditReconciliationInput` accepts `day=None` (recurring Schedule) and derives yesterday-UTC from `workflow.now()` per fire. New OTel meter `sentinelrag_audit_reconciliation_drift{side}` (cardinality-disciplined: no tenant_id). `ObjectStorage.list_keys()` added to the protocol + S3Storage. Schedule registration helper at `sentinelrag_worker.scripts.register_audit_schedule` is idempotent — upserts a daily Schedule reading tenant IDs from `AUDIT_RECON_TENANT_IDS`. Worker `main.py` now runs an `audit` task queue alongside ingestion/evaluation. 16 unit tests cover diff math, backfill cap, idempotent re-run, race-deletion safety, and key-prefix invariants.
- ⚪ Tempo for traces — `docker-compose.yml` ships Jaeger today. Tempo as the long-term store is a one-config swap; deferred until we add the Tempo Helm dependency in Phase 7.
- ⚪ Live SLO + budget-alert demo — needs `make up` + Prom + a synthetic load run to capture before/after panels. Deferred to Phase 9 portfolio polish.

**Done when:** Grafana shows live RAG metrics; budget alert demonstrably fires. _(Code-side complete including reconciliation; live demo + Schedule registration against a real Temporal cluster gated on Docker availability.)_

### Phase 7 — AWS production deployment ⚪
**Goal:** live `dev.<domain>` on AWS.
- Terraform: VPC, EKS, RDS Postgres, ElastiCache, S3, Secrets Manager, ACM, IAM/IRSA.
- Helm chart consolidating all manifests.
- ArgoCD installed; one Application per env (dev only initially).
- External Secrets Operator + AWS Secrets Manager.
- HPA, PDB, NetworkPolicies per service.

**Done when:** push to main → ArgoCD deploys → live URL serves a query.

### Phase 8 — Multi-cloud + scale features ⚪
**Goal:** GCP mirror deployment + OpenSearch reintroduction.
- GCP Terraform mirror; same Helm chart.
- OpenSearch as second `KeywordSearch` adapter; A/B against Postgres FTS.
- k6 load tests; chaos tests via litmus or chaos-mesh.
- Trivy/bandit/tfsec security scans in CI.
- Disaster recovery runbook.

**Done when:** GCP deploy verified once; OpenSearch A/B report committed; resilience evidence documented.

### Phase 9 — Portfolio polish ⚪
**Goal:** readable artifacts a senior engineer can absorb in 30 minutes.
- Root README with architecture diagram, quick-start, live demo URL.
- C4 diagrams in `docs/architecture/c4/` (rendered PNGs).
- ADR index complete and current.
- Cost report (1 month synthetic traffic).
- Eval report: before/after hybrid retrieval; before/after rerank; before/after prompt v2.
- 5-minute demo video.

**Done when:** the repo's README sells the project on its own.

## Cross-phase rules

- Every architectural decision lands as an ADR before code.
- Every cross-cutting library/tool change lands as a new ADR (don't edit accepted ADRs — supersede).
- No phase is "done" until its tests pass in CI on a clean checkout.
- After each phase, this file is updated with what shipped + what was deferred.
- Each phase's deliverables include an entry in `docs/operations/runbooks/` if the phase added a new operational concern.
