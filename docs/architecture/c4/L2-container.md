# C4 L2 — Container Diagram

The deployable units inside SentinelRAG and the protocols between them.

```mermaid
C4Container
    title SentinelRAG — Container Diagram

    Person(end_user, "End user")
    Person(tenant_admin, "Tenant admin")

    System_Boundary(sentinelrag, "SentinelRAG") {
      Container(frontend, "frontend", "Next.js 15 + NextAuth", "App-Router UI; query playground; admin pages")
      Container(api, "api", "FastAPI + Pydantic v2 + SQLAlchemy 2.0 async", "All HTTP routes; in-process RAG orchestrator; cost gate; audit dual-write")
      Container(worker, "temporal-worker", "Python + temporalio", "Ingestion, evaluation, audit-reconciliation, OpenSearch-drift workflows")
      Container(temporal, "Temporal cluster", "Temporal frontend + history + matching + Postgres-backed state", "Durable workflow engine")
      ContainerDb(postgres, "Postgres 16 + pgvector", "RDS / Cloud SQL", "Tenants, RBAC, RLS, query sessions, audit mirror, vector store, FTS index")
      ContainerDb(redis, "Redis 7", "ElastiCache / Memorystore", "Prompt cache, JWKS cache, rate-limit counters")
      ContainerDb(object_store, "Object storage", "S3 / GCS", "Documents (versioned) + audit (Object Lock COMPLIANCE / locked retention)")
      ContainerDb(opensearch, "OpenSearch 2.x", "Managed OpenSearch / self-hosted", "Phase-8 second KeywordSearch backend; Postgres remains RBAC SoT")
    }

    System_Ext(keycloak, "Keycloak", "OIDC")
    System_Ext(litellm_targets, "LiteLLM targets", "Anthropic / OpenAI / Ollama")
    System_Ext(unleash, "Unleash", "Feature flags")
    System_Ext(otel, "OTel Collector", "Tempo / Prometheus / Loki")
    System_Ext(eso, "External Secrets Operator", "Materializes Secrets Manager / Secret Manager into K8s Secrets")

    Rel(end_user,    frontend,   "HTTPS / SSE for trace stream")
    Rel(tenant_admin, frontend,  "HTTPS")
    Rel(frontend,    api,        "REST + Pydantic contracts", "HTTPS")
    Rel(frontend,    keycloak,   "OAuth2 PKCE", "HTTPS")

    Rel(api, postgres,    "asyncpg pool; SET LOCAL app.current_tenant_id; HNSW + GIN", "TCP")
    Rel(api, redis,       "Cache-aside")
    Rel(api, object_store, "Doc upload; audit dual-write")
    Rel(api, opensearch,  "Optional KeywordSearch backend (flagged)")
    Rel(api, temporal,    "Schedule ingestion + eval workflows")
    Rel(api, litellm_targets, "Embedding + generation via LiteLLM")
    Rel(api, keycloak,    "JWKS verify (cached)")
    Rel(api, unleash,     "Flag evaluation")
    Rel(api, otel,        "OTLP traces + metrics + logs")

    Rel(worker, temporal,    "Pulls task queues: ingestion, evaluation, audit")
    Rel(worker, postgres,    "Persists chunks, embeddings, eval results")
    Rel(worker, object_store, "Reads docs; writes index records; reconciles audit")
    Rel(worker, opensearch,  "Bulk-index chunks; reconcile drift")
    Rel(worker, litellm_targets, "Embedding for ingestion; LLM-as-judge for evals")
    Rel(worker, otel,        "OTLP")

    Rel(eso, api, "Mounts secrets")
    Rel(eso, worker, "Mounts secrets")
    Rel(eso, frontend, "Mounts NextAuth + Keycloak secrets")
```

## Why containers split this way

- **`api` is the cost-and-RBAC chokepoint.** Every privileged action passes through it; this is what makes the audit trail credible. The orchestrator runs in-process (ADR-0021) so the chokepoint and the work are co-located.
- **`temporal-worker` is the only place activities run.** Three task queues — `ingestion`, `evaluation`, `audit` — share one worker process today; production may split.
- **`opensearch` is optional.** ADR-0026: it's a flagged second backend behind the same `KeywordSearch` protocol. Postgres FTS is the always-on backend; OpenSearch is A/B-able.
- **`temporal` is its own cluster.** Self-managed via the upstream Helm chart, NOT bundled into the SentinelRAG chart (ADR-0023) — its sub-chart graph is too heavy.

## Inter-container protocols

| Pair | Protocol | Why |
|---|---|---|
| frontend → api | REST + Pydantic v2 contracts | ADR-0009 (overrides spec's gRPC). Same wire shape as we'd publish to third-party SDK. |
| api → temporal | Temporal SDK | Native client. Workflows are durable, type-safe across language runtimes. |
| api → object_store | S3 API (AWS) / GCS API (GCP) | Same SDK shape via `boto3` / `google-cloud-storage`. Provider switch is a values-overlay change. |
| api → postgres | asyncpg | Async-native. Pool sized to match `max_concurrent_workflow_tasks` × `worker.replicas`. |
| api → litellm targets | LiteLLM HTTP | One library, every provider. Cost + token accounting in one place. |

## Related ADRs

- [ADR-0009](../adr/0009-rest-not-grpc.md) — REST + Pydantic over gRPC
- [ADR-0021](../adr/0021-retrieval-embedded-v1.md) — Retrieval embedded in `api` for v1
- [ADR-0023](../adr/0023-helm-chart-shape.md) — Helm chart shape (which containers ship in the chart)
- [ADR-0026](../adr/0026-opensearch-reintroduction.md) — OpenSearch as parallel adapter
