# SentinelRAG — progress snapshot

> One-page summary of where the build stands. The full live ledger is in
> [`docs/architecture/PHASE_PLAN.md`](docs/architecture/PHASE_PLAN.md);
> this file is the recruiter-readable cover sheet.

**Last updated:** 2026-04-29 — all 10 phases code-side complete.

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
- **75 unit tests passing** (1 pre-existing flake tracked).
- **5 GitHub Actions workflows**: `ci.yml`, `security.yml`, `perf-smoke.yml`, `dr-backup-verify.yml`, `build-images.yml`.
- **4 operations runbooks** at `docs/operations/runbooks/`: deployment-aws, deployment-gcp, cluster-bootstrap, disaster-recovery.
- **5 Helm values overlays**: `values.yaml` (defaults), `values-{local,dev,prod,gcp-dev}.yaml`. All `helm lint` clean.
- **15 Terraform modules** (8 AWS + 7 GCP) under `infra/terraform/<cloud>/modules/`.

## What's done in code

✅ Multi-tenant data plane with RLS + RBAC at retrieval time
✅ Hybrid retrieval (BM25 + pgvector HNSW + RRF + bge-reranker)
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

## Where to read in detail

- **Build status (live ledger):** [`docs/architecture/PHASE_PLAN.md`](docs/architecture/PHASE_PLAN.md)
- **Why each decision was made:** [`docs/architecture/adr/`](docs/architecture/adr/) — 30 ADRs
- **Architecture diagrams:** [`docs/architecture/c4/`](docs/architecture/c4/) — Mermaid, GitHub-rendered
- **Deployment runbooks:** [`docs/operations/runbooks/`](docs/operations/runbooks/)
- **Working with this repo:** [`CLAUDE.md`](CLAUDE.md) — locked stack, architectural pillars, footguns
- **Repository tour, quick-start:** [`README.md`](README.md)

## Verification this session

- `uv run pytest -m unit` → 75 passed, 1 pre-existing flake
- `uv run ruff check apps packages scripts tests` → clean
- `helm lint` against all 5 values overlays → clean
- All cross-references between README ↔ runbooks ↔ ADRs ↔ Terraform modules ↔ Helm chart verified
