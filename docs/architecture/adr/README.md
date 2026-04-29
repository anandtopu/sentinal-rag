# Architecture Decision Records

This directory holds the architectural decisions for SentinelRAG. We use the [MADR](https://adr.github.io/madr/) format (Markdown Architectural Decision Records).

## Conventions

- Filenames: `NNNN-kebab-case-title.md` (zero-padded, immutable once merged).
- Each ADR is **immutable** once accepted. To revise: write a new ADR that supersedes the old one and update the old ADR's status to `Superseded by ADR-NNNN`.
- ADRs are short on purpose — focused on one decision with clear trade-offs.
- Status values: `Proposed`, `Accepted`, `Superseded by ADR-NNNN`, `Deprecated`.
- When an ADR overrides one of the design docs (`Enterprise_RAG_*.md`), call this out explicitly under "Notes on the design docs".

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-monorepo-uv-workspace.md) | Monorepo with uv workspaces | Accepted |
| [0002](0002-python-tooling.md) | Python tooling: uv + ruff + pyright + pre-commit | Accepted |
| [0003](0003-pgvector-hnsw.md) | pgvector with HNSW indexes (overrides spec's ivfflat) | Accepted |
| [0004](0004-postgres-fts-over-opensearch.md) | Postgres FTS for v1 BM25 search; OpenSearch deferred | Accepted |
| [0005](0005-litellm-gateway.md) | LiteLLM as the unified LLM gateway | Accepted |
| [0006](0006-bge-reranker.md) | bge-reranker-v2-m3 as default reranker | Accepted |
| [0007](0007-temporal-over-celery.md) | Temporal for durable workflows (overrides spec's Celery) | Accepted |
| [0008](0008-keycloak-auth.md) | Keycloak self-hosted for OAuth2/JWT | Accepted |
| [0009](0009-rest-not-grpc.md) | REST + Pydantic between services (overrides C4 L4 gRPC) | Accepted |
| [0010](0010-layered-hallucination-detection.md) | Layered hallucination detection (cheap → expensive cascade) | Accepted |
| [0011](0011-multi-cloud-strategy.md) | AWS primary, GCP mirror, Azure ADR-only | Accepted |
| [0012](0012-helm-argocd-deployment.md) | Helm chart + ArgoCD GitOps for K8s | Accepted |
| [0013](0013-unstructured-parsing.md) | `unstructured` library for document parsing | Accepted |
| [0014](0014-hybrid-llm-strategy.md) | Hybrid LLM strategy: Ollama default, OpenAI opt-in | Accepted |
| [0015](0015-raw-text-in-object-storage.md) | Raw document text stored in object storage, not Postgres | Accepted |
| [0016](0016-immutable-audit-dual-write.md) | Audit log dual-write to Postgres + S3 Object Lock | Accepted |
| [0017](0017-frontend-nextjs-app-router.md) | Next.js 15 App Router for frontend | Accepted |
| [0018](0018-feature-flags-unleash.md) | Unleash self-hosted for feature flags | Accepted |
| [0019](0019-evaluation-framework-ragas.md) | `ragas` + custom evaluators for evaluation | Accepted |
| [0020](0020-multi-dim-embeddings.md) | Multi-dimension embeddings via per-dimension columns | Accepted |
| [0021](0021-retrieval-embedded-v1.md) | Retrieval embedded in-process for v1; extract in Phase 7 | Accepted |
| [0022](0022-cost-budgets-soft-hard-caps.md) | Per-tenant cost budgets with soft / hard caps | Accepted |
| [0023](0023-helm-chart-shape.md) | Helm chart shape: single chart, in-template workload blocks, cloud switch | Accepted |
| [0024](0024-terraform-layout.md) | Terraform layout: env-per-dir + shared modules, no Terragrunt | Accepted |
| [0025](0025-gcp-parity.md) | GCP parity: function-named modules, identical Helm chart, per-cloud values overlay | Accepted |
| [0026](0026-opensearch-reintroduction.md) | OpenSearch reintroduction: parallel adapter behind KeywordSearch protocol; Postgres-resolved RBAC | Accepted |
| [0027](0027-load-and-chaos-testing.md) | Load + chaos testing: k6 with SLO-bound thresholds; Chaos Mesh game-day workflow | Accepted |
| [0028](0028-disaster-recovery.md) | DR: tiered RPO/RTO commitments, active-passive cross-cloud, daily automated backup verification | Accepted |
| [0029](0029-portfolio-polish.md) | Portfolio polish: Mermaid C4, harness-with-placeholder reports, README as the front door | Accepted |
| [0030](0030-cluster-bootstrap.md) | Cluster bootstrap: values overlays + ArgoCD Application manifests, not bundled into the SentinelRAG chart | Accepted |
