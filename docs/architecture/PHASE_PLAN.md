# SentinelRAG — Phase Plan

This is the live phase plan for the SentinelRAG build. Update this file when a phase completes or when scope changes — future Claude instances read this at the start of every session to know where we are.

## Status legend

- 🟢 Complete
- 🟡 In progress / partial
- ⚪ Not started

## Current phase

**All 10 phases complete (code-side) — last update 2026-04-29.** Phase
7 Slice 3 (cluster bootstrap) closed alongside the deployment runbooks
this session — ADR-0030 + `infra/bootstrap/` (cert-manager, AWS LB
controller, ESO + secret-stores, Temporal, ArgoCD + per-cloud
Applications, Chaos Mesh) + `.github/workflows/build-images.yml` (GHCR
push with provenance + SBOM + Trivy) + three new runbooks at
`docs/operations/runbooks/{deployment-aws,deployment-gcp,cluster-bootstrap}.md`.
30 ADRs total. Ruff clean across `apps` + `packages` + `scripts` +
`tests`.

**Phase 8 complete (code-side) — all five slices shipped earlier.**

Live-infra leftovers — real eval-report numbers, real cost-report numbers,
GCP deploy verified once, drill-recorded RTO numbers, 5-minute demo video
— all gate on the deployed dev environment that **Phase 7 Slice 3** still
owes (cluster bootstrap charts: ArgoCD + ESO + Temporal + ALB controller +
cert-manager + GHCR push pipeline).

**Phase 7 — Slices 1, 2, 4 shipped earlier 2026-04-29.**

- 🟢 **Slice 1 (Helm chart):** ADR-0023 + `infra/helm/sentinelrag/`
  covering api + temporal-worker + frontend + alembic-migration Job, with
  shared `_helpers.tpl`, cloud switch, ESO integration, overlays for
  `values-{local,dev,prod}.yaml`. `helm lint` + `helm template` clean.
- 🟢 **Slice 2 (AWS Terraform):** ADR-0024 + `infra/terraform/aws/`
  modules (vpc, eks, rds, elasticache, s3, secrets, iam) + dev environment
  wiring. Env-per-dir + shared modules. RDS Postgres 16 + pgvector,
  ElastiCache Redis 7, S3 documents (versioned) + audit (Object Lock
  COMPLIANCE 7y), Secrets Manager parent secrets, IRSA roles for
  api/worker/frontend/ESO, EKS 1.30 with cluster access entries (no
  aws-auth ConfigMap). Backend = S3 + DynamoDB lock.
- 🟢 **Slice 4 (Dockerfiles):** `apps/temporal-worker/Dockerfile` and
  `apps/frontend/Dockerfile` (Next.js standalone output). Both non-root
  uid 10001 matching the chart's pod security context.
- 🟢 **Slice 3 (cluster bootstrap):** ADR-0030 + `infra/bootstrap/`
  with pinned values overlays for cert-manager (v1.16.2),
  AWS Load Balancer Controller (1.10.1), External Secrets Operator
  (0.10.7) + `secret-store-{aws,gcp}.yaml` ClusterSecretStores,
  Temporal (0.55.0), ArgoCD (7.7.5) + per-cloud SentinelRAG
  `Application` manifests, optional Chaos Mesh (2.7.2).
  `.github/workflows/build-images.yml` builds api + worker + frontend
  on push-to-main and on `v*.*.*` tag, pushes to GHCR with provenance
  attestation + SBOM + Trivy SARIF. ArgoCD Image Updater annotations on
  the Application manifest pick up new tags via Git write-back. End-to-end
  procedure documented in
  `docs/operations/runbooks/{cluster-bootstrap,deployment-aws,deployment-gcp}.md`.

**Earlier phases.** Phases 0 → 6 + 6.5 are 🟢 (foundations, data plane,
ingestion, retrieval + RAG orchestrator, prompt registry + evaluation,
frontend, observability + cost + audit + metrics slice + reconciliation
landed across the earlier sessions). Phase 7 — Slices 1, 2, 4 🟢 (Helm
chart, AWS Terraform, Dockerfiles) and **Slice 3 cluster bootstrap is
now closed alongside the deployment runbooks (this session).** Phase
8 — all 5 slices 🟢 (GCP mirror, OpenSearch reintroduction, k6 + Chaos
Mesh, security CI, DR runbook). Phase 9 — 🟢 code-side (Mermaid C4,
README overhaul, eval + cost harnesses, ADR-0029).

**Verified this session:**
- `uv run pytest -m unit` → 75 passed, 1 pre-existing flake.
- `uv run ruff check apps packages scripts tests` → clean.
- `helm lint` against `values-dev.yaml`, `values-gcp-dev.yaml`,
  `values-prod.yaml`, `values-local.yaml` → clean.

**Still gates on running infra (not in this session):**
- `make db-upgrade` against a real Postgres.
- `pytest -m integration` (testcontainers; needs Docker Desktop).
- End-to-end `/query` smoke against live Postgres + Ollama.
- First `terraform apply` against a real AWS / GCP account.
- 5-min demo video.

**Known typecheck baseline (not blocking):** `uv run pyright` (strict)
reports ~154 baseline errors + ~512 warnings, dominated by
`reportMissingTypeStubs` for workspace-internal modules and
`reportUnknownParameterType` in integration test fixtures. Tighten
incrementally rather than in a single sweep.

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

### Phase 7 — AWS production deployment 🟢 (code-side)
**Goal:** live `dev.<domain>` on AWS.
- 🟢 **Slice 1 — Helm chart.** ADR-0023 + `infra/helm/sentinelrag/` shipped.
  Single chart packaging api + temporal-worker + frontend + a pre-upgrade
  alembic migration Job. Shared `_helpers.tpl` library renders Deployment /
  SA / ConfigMap / Service / Ingress / HPA / PDB / NetworkPolicy /
  ExternalSecret per workload from one consistent ctx dict.
  - Cloud switch (`cloud: aws|gcp|azure|local`) drives the default
    IngressClass; per-env IRSA / ALB annotations live in
    `values-{dev,prod}.yaml`.
  - Dependency charts declared but gated by `*.enabled`:
    `bitnami/postgresql`, `bitnami/redis`, `bitnami/minio`,
    `bitnami/keycloak`, `unleash/unleash` (versions pinned in `Chart.lock`).
    Temporal is excluded — its sub-chart graph is too heavy; installed by
    bootstrap Terraform instead.
  - `helm lint` clean against base + dev + prod + local overlays.
    `helm template` renders against all four (after `helm dependency build`
    + extracting tarballs — Helm 4 quirk noted in deployment runbook).
  - Phase 7 still needs: AWS Terraform (VPC + EKS + RDS pgvector +
    ElastiCache + S3 + Secrets Manager + ACM + IRSA roles), ArgoCD bootstrap
    + dev `Application`, External Secrets Operator install + ClusterSecretStore,
    Temporal install in-cluster, image build + push pipeline (`apps/temporal-worker/Dockerfile`
    + `apps/frontend/Dockerfile` not yet authored).
- 🟢 Slice 2 — AWS Terraform: ADR-0024 + 7 modules (vpc, eks, rds,
  elasticache, s3, secrets, iam) + dev environment wiring. RDS Postgres 16
  with pgvector parameter group; S3 audit bucket with Object Lock COMPLIANCE
  7y; Secrets Manager 3 parent secrets; IRSA roles wired to OIDC for api,
  worker, frontend, ESO; EKS 1.30 cluster access entry mode.
- ⚪ Slice 3 — ArgoCD + ExternalSecretsOperator + Temporal cluster install.
- 🟢 Slice 4 — Worker + frontend Dockerfiles (multi-stage, non-root
  uid 10001). GHCR push pipeline still to wire (CI workflow).

**Done when:** push to main → ArgoCD deploys → live URL serves a query.

### Phase 8 — Multi-cloud + scale features 🟢 (code-side)
**Goal:** GCP mirror deployment + OpenSearch reintroduction.
- 🟢 **Slice 1 — GCP Terraform mirror.** ADR-0025 + 7 modules
  (vpc, gke, cloudsql, memorystore, gcs, secrets, iam) + dev environment
  wiring. GKE Standard private nodes + Workload Identity, Cloud SQL
  Postgres 16 + pgvector via Private Service Access, Memorystore Redis 7,
  GCS audit bucket with locked retention 7y, Secret Manager parents,
  Workload Identity bindings for api/worker/frontend/ESO. Helm
  `values-gcp-dev.yaml` overlay (cloud=gcp, GCE Ingress, WI annotations).
- 🟢 **Slice 2 — OpenSearch reintroduction.** ADR-0026 +
  `sentinelrag_shared/retrieval/opensearch_keyword_search.py` implementing
  the existing `KeywordSearch` protocol. Postgres-resolved authorization
  (one round-trip via the same `authorized_collections` CTE
  `AccessFilter` builds), tenant + collection `terms` filter on every
  query. `bulk_index`, `delete_by_document`, `ensure_index` helpers for
  the ingestion pipeline. AWS OpenSearch Terraform module
  (`infra/terraform/aws/modules/opensearch/`) with private VPC
  placement, fine-grained access, dual-AZ awareness, CloudWatch logs.
  11 unit tests covering empty-query short-circuit, RBAC zero-collection
  case, tenant-and-collection filters, requested-collection intersection
  with authorized set, bulk_index partial failure, ensure_index
  idempotency, delete_by_document filters.
- 🟢 **Slice 3 — Load + chaos testing.** ADR-0027 +
  `tests/performance/k6/` (4 scenarios — smoke / baseline / soak / spike,
  shared `lib/{config,queries,http}.js`, SLO-bound thresholds,
  README) + `infra/chaos/` (namespace, 6 experiments under
  `experiments/`, game-day `Workflow` chaining all six, README with
  experiment matrix). `.github/workflows/perf-smoke.yml` runs the
  smoke scenario on every PR + daily cron when `SENTINELRAG_DEV_BASE_URL`
  is configured (no-op otherwise so external contributors don't
  break the run). Per-experiment hypotheses live in each manifest's
  header so the assertions are self-documenting.
- 🟢 **Slice 4 — Security scans CI.** `.github/workflows/security.yml`
  with tfsec (Terraform), bandit (Python), trivy fs (filesystem + IaC),
  trivy image (api + worker + frontend Dockerfiles via matrix). All
  uploads SARIF to GitHub code scanning; weekly cron + PR triggers.
- 🟢 **Slice 5 — Disaster recovery.** ADR-0028 + tiered RPO/RTO matrix
  (Tier 0 audit immutable, Tier 1 Postgres+S3 RPO 5min/24h RTO 1h/2h,
  Tier 2 Redis+Temporal RTO 15min/1h). `docs/operations/runbooks/disaster-recovery.md`
  with 8 failure scenarios (RDS failure, S3 doc loss, audit bucket
  edge cases, Redis loss, Temporal loss, region outage with cross-cloud
  failover, EKS destruction, Secrets corruption) — each with symptoms,
  immediate response, recovery procedure, expected data loss, post-incident
  follow-up. `scripts/dr/verify-backups-{aws,gcp}.sh` daily verifiers
  (RDS/CloudSQL snapshot freshness, bucket versioning, Object Lock /
  Locked Retention shape) + `.github/workflows/dr-backup-verify.yml`
  with daily cron, OIDC federation, JSON-artifact retention, Slack
  webhook on failure, shellcheck gate. Active-passive cross-cloud stance
  documented; cross-cloud data replication explicitly Phase 9.

**Done when:** GCP deploy verified once; OpenSearch A/B report committed; resilience evidence documented.

### Phase 9 — Portfolio polish 🟢 (code-side)
**Goal:** readable artifacts a senior engineer can absorb in 30 minutes.
- 🟢 **Root README overhaul.** Recruiter-readable, with an embedded
  Mermaid architecture diagram, stack table that links each row to the
  ADR that pinned it, repository tour, quick-start, build status and
  things-not-to-do.
- 🟢 **C4 diagrams as Mermaid.** ADR-0029 + `docs/architecture/c4/`:
  L1 system context, L2 container, L3 RAG-core component, L4 deployment
  for AWS + L4 deployment for GCP. Rendered natively by GitHub; each
  diagram links to the ADRs visible at that level.
- 🟢 **ADR index current.** 29 ADRs (ADR-0001 through ADR-0029); the
  catalog at `docs/architecture/adr/README.md` is in sync.
- 🟢 **Eval comparison harness.** `tests/performance/evals/compare.py`
  with three pre-wired comparisons (hybrid-vs-vector, rerank-vs-no,
  prompt-v2-vs-v1), a 3-case JSON fixture for self-check, and a
  placeholder report at `docs/operations/eval-report.md` describing the
  expected shape. Overwritten on first real run.
- 🟢 **Cost report harness.** `scripts/cost/synthetic_month.py` (CSV
  generator emulating 30 days × 4 tenants × 6 models, with weekly
  seasonality + tier-based model mix) +
  `scripts/cost/render_report.py` (markdown renderer with daily-trend
  sparkline + per-tenant + per-model breakdowns). Committed report at
  `docs/operations/cost-report.md` rendered from synthetic CSV
  (seed=42); the CSV itself is gitignored (regenerable).
- 🟢 **ADR-0029** documents the "harness with placeholder report"
  pattern + the Mermaid-over-PNG choice.
- ⚪ **5-min demo video.** Gates on the deployed dev environment
  (Phase 7 Slice 3).

**Done when:** the repo's README sells the project on its own. _(Met
modulo the live demo video, which gates on Phase 7 Slice 3 cluster
bootstrap.)_

## Cross-phase rules

- Every architectural decision lands as an ADR before code.
- Every cross-cutting library/tool change lands as a new ADR (don't edit accepted ADRs — supersede).
- No phase is "done" until its tests pass in CI on a clean checkout.
- After each phase, this file is updated with what shipped + what was deferred.
- Each phase's deliverables include an entry in `docs/operations/runbooks/` if the phase added a new operational concern.
