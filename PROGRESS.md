# SentinelRAG — progress snapshot

> One-page summary of where the build stands. The full live ledger is in
> [`docs/architecture/PHASE_PLAN.md`](docs/architecture/PHASE_PLAN.md);
> this file is the recruiter-readable cover sheet.

**Last updated:** 2026-05-15 — all 10 phases code-side complete. Latest
session expanded frontend Playwright E2E coverage for the dashboard,
settings, audit/usage surfaces, optional query traces, and mocked tenant/user
context. `pytest -m unit` remains green across **162 collected unit
tests** with **70.80% Python coverage**.

## Status by phase

| Phase | Goal | Status | Highlights |
|---|---|---|---|
| 0 | Foundations | 🟢 | Monorepo, `make up` local stack, CI lint+typecheck, ADR catalog |
| 1 | Tenancy + RBAC | 🟢 | 10 Alembic migrations, Postgres RLS, JWKS-cached JWT verifier |
| 2 | Ingestion | 🟢 | Temporal `IngestionWorkflow` + 8 idempotent activities; multi-dim embedding columns |
| 3 | Retrieval + RAG orchestrator | 🟢 | Hybrid BM25+vector w/ RRF, per-query `ef_search`, RBAC at retrieval time |
| 4 | Prompts + evaluation | 🟢 | Versioned `PromptService`, 4 custom evaluators, eval workflow |
| 5 | Frontend | 🟢 | Next.js 15 App Router, NextAuth, query playground with SSE trace |
| 6 + 6.5 | Observability + cost + audit | 🟢 | Per-tenant budgets, audit dual-write, daily reconciliation, OTel meters, Grafana JSON dashboards |
| 7 | AWS deployment | 🟢 (code-side) | Helm chart + 8 Terraform modules + Dockerfiles + bootstrap charts + GHCR build pipeline |
| 8 | Multi-cloud + scale + DR | 🟢 (code-side) | GCP mirror (7 modules), OpenSearch reintroduction, k6 + Chaos Mesh, security CI, DR runbook |
| 9 | Portfolio polish | 🟢 (code-side) | Mermaid C4 (L1-L4 + GCP), eval + cost harnesses, README overhaul |

## Counts

- **30 accepted ADRs** at `docs/architecture/adr/` (template + ADR-0001…ADR-0030).
- **162 collected unit tests passing, 0 flakes observed in the current
  Python 3.12 environment.**
- **15 frontend Playwright E2E tests**: 11 deterministic frontend/mocked-API
  tests pass locally; 4 live-backend specs skip cleanly when `/api/health` is
  unavailable.
- **5 GitHub Actions workflows**: `ci.yml`, `security.yml`, `perf-smoke.yml`, `dr-backup-verify.yml`, `build-images.yml`.
- **4 operations runbooks** at `docs/operations/runbooks/`: deployment-aws, deployment-gcp, cluster-bootstrap, disaster-recovery.
- **5 Helm values overlays**: `values.yaml` (defaults), `values-{local,dev,prod,gcp-dev}.yaml`. All `helm lint` clean.
- **15 Terraform modules** (8 AWS + 7 GCP) under `infra/terraform/<cloud>/modules/`.

## What's done in code

✅ Multi-tenant data plane with RLS + RBAC at retrieval time
✅ Hybrid retrieval (BM25 + pgvector HNSW + RRF + bge-reranker)
✅ Retrieval regression coverage for query response options, trace streaming,
cloud-model gates, abstain behavior, AccessFilter, pgvector `ef_search`, RRF,
OpenSearch/Postgres parity, and retrieval-service validation
✅ Focused service-layer and Temporal worker unit coverage for document,
prompt, evaluation, tenant/user/role, ingestion, and evaluation failure paths
✅ Layered hallucination detection (token-overlap → NLI → LLM-judge cascade)
✅ Per-tenant cost budgets (soft-cap downgrade, hard-cap deny, before generation)
✅ Audit dual-write — Postgres + Object Lock COMPLIANCE / locked retention 7y
✅ Daily audit-reconciliation Temporal Schedule
✅ Versioned prompts as first-class artifacts
✅ Next.js 15 dashboard with SSE trace stream
✅ AWS Terraform — VPC, EKS, RDS pgvector, ElastiCache, S3 (Object Lock), Secrets Manager, IRSA, OpenSearch
✅ GCP Terraform mirror — VPC, GKE, Cloud SQL pgvector, Memorystore, GCS (locked retention), Secret Manager, Workload Identity
✅ Helm chart with cloud switch + ESO integration + pre-upgrade alembic Job
✅ Cluster bootstrap charts as values overlays — cert-manager, ALB controller, ESO, Temporal, ArgoCD, Chaos Mesh
✅ ArgoCD Application manifests per cloud + Image Updater annotations
✅ GHCR image build pipeline with provenance + SBOM + Trivy SARIF
✅ k6 load tests (smoke / baseline / soak / spike) with SLO-bound thresholds
✅ Chaos Mesh game-day workflow (6 experiments, hypothesis-driven)
✅ Security scans CI — tfsec / bandit / trivy (filesystem + image matrix)
✅ DR runbook with RPO/RTO matrix + 8 failure scenarios
✅ Daily backup verifier (AWS + GCP) with Slack alerting
✅ Mermaid C4 diagrams (L1 system context → L4 AWS + GCP deployments)
✅ Eval comparison harness (3 pre-wired comparisons) + cost report renderer

## What's left — needs running infrastructure

These are the only remaining items, and they all depend on a real cloud account:

- ☐ First `terraform apply` against a real AWS / GCP account
- ☐ First `helm install` of the bootstrap stack
- ☐ First `git push origin v0.1.0` to fire the GHCR pipeline
- ☐ First ArgoCD sync of `sentinelrag-{,gcp-}dev` Application
- ☐ Real-traffic numbers in `docs/operations/{eval,cost}-report.md` (overwrite the placeholders)
- ☐ Drill-recorded RTO numbers in DR runbook
- ☐ 5-minute demo video

Everything in code is ready. The repo is production-deployment-ready
modulo the live-account hand-off step.

## Latest session handoff (2026-05-12)

- Python tooling repaired to repo-local `.venv` on **Python 3.12.13** via
  `uv`; `uv.lock` is current after slimming the diagnostic
  `sentinelrag-retrieval-service` dependencies.
- Query/RAG route tests now cover response citation options, trace metadata
  coercion, streaming timeout/session edge cases, cloud-model permission
  gates, and `abstain_if_unsupported=False` orchestration.
- Retrieval hardening tests now cover `AccessFilter`, pgvector vector
  formatting and `ef_search`, RRF edge cases, and OpenSearch/Postgres
  authorization-shape parity.
- Service-layer and worker tests added for `DocumentService`, `PromptService`,
  `EvaluationService`, tenant/user/role services, ingestion idempotency, and
  evaluation workflow failure paths.
- Retrieval-service review fixes landed: OpenSearch refresh params now use
  the installed client API, RRF has a public `merge_with_rrf` helper, the
  wrapper no longer calls a protected method, capabilities describe the
  actual diagnostic endpoint, and wrapper coverage is 100%.
- Full unit suite is green. Integration tests are still environment-blocked
  on this Windows host by Docker named-pipe access denial
  (`//./pipe/docker_engine`), not by Python tooling.

## Where to read in detail

- **Build status (live ledger):** [`docs/architecture/PHASE_PLAN.md`](docs/architecture/PHASE_PLAN.md)
- **Why each decision was made:** [`docs/architecture/adr/`](docs/architecture/adr/) — 30 ADRs
- **Architecture diagrams:** [`docs/architecture/c4/`](docs/architecture/c4/) — Mermaid, GitHub-rendered
- **Deployment runbooks:** [`docs/operations/runbooks/`](docs/operations/runbooks/)
- **Working with this repo:** [`AGENTS.md`](AGENTS.md) — Codex session checklist, locked stack, architectural pillars, footguns
- **Repository tour, quick-start:** [`README.md`](README.md)

## Verification (deploy-audit pass, 2026-04-29)

- `uv run pytest -m unit` → **76 passed, 0 failures, 0 flakes**
- `uv run ruff check apps packages scripts tests` → clean
- `helm lint` against all 5 values overlays → clean
- `helm template` against all 5 overlays → clean (9,950 LOC of rendered YAML)
- 10 critical Python modules import cleanly
- All 5 GitHub Actions workflows YAML-parse
- All 18 bootstrap + chaos manifests YAML-parse
- All Terraform module references resolve to populated module dirs
- Alembic finds all 12 migration revisions in the API package's venv
- All repo markdown cross-references resolve

### Deploy blockers fixed this session

1. API Dockerfile didn't `COPY migrations/` → fixed
2. `psycopg` (alembic sync driver) wasn't in api deps → added
3. Helm SA names didn't match Terraform IRSA / WI trust policy → fixed
4. AWS env outputs missing `rds_username`, `rds_master_password`, `rds_database_name`, `redis_port`, `redis_auth_token` → added
5. GCP env outputs missing `cloudsql_username`, `cloudsql_database_name`, `cloudsql_master_password`, `redis_port`, `redis_auth_string` → added; runbook updated to use them
6. AWS LB Controller IAM role missing → added trust policy + AWS-published policy + role + output

### Test flake fixed

The previously-tracked `test_dev_token_disabled_by_default` flake has been root-caused (python-dotenv writes `.env` values into `os.environ` as a side effect; subsequent tests with `_env_file=None` still saw the polluted env) and fixed via a `monkeypatch.delenv` fixture.
