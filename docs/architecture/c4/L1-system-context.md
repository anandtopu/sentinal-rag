# C4 L1 — System Context

SentinelRAG as a single box, with the people and external systems it talks to.

```mermaid
C4Context
    title SentinelRAG — System Context

    Person(end_user, "End user", "Submits queries via the web UI; reads grounded, cited answers")
    Person(tenant_admin, "Tenant admin", "Manages users, roles, collections, prompt templates, budgets")
    Person(eval_engineer, "Eval engineer", "Authors eval datasets; runs comparison reports; tunes prompts")
    Person(sre, "SRE / on-call", "Reads dashboards, runs DR drills, applies chaos workflows")

    System(sentinelrag, "SentinelRAG", "Multi-tenant, RBAC-aware, evaluation-driven enterprise RAG platform")

    System_Ext(idp, "Keycloak", "OIDC / OAuth2 identity provider; tenant-aware realm")
    System_Ext(llm_apis, "LLM APIs", "Anthropic, OpenAI, Ollama (self-hosted)")
    System_Ext(object_store, "S3 / GCS / MinIO", "Documents + audit object storage with Object Lock / locked retention")
    System_Ext(observability, "OTel Collector → Tempo / Prometheus / Loki", "Traces, metrics, logs")
    System_Ext(flags, "Unleash", "Feature flags incl. prompt routing")
    System_Ext(secrets, "AWS Secrets Manager / GCP Secret Manager", "Workload secrets, materialized into K8s via External Secrets Operator")

    Rel(end_user,    sentinelrag, "Queries, uploads docs", "HTTPS / Next.js")
    Rel(tenant_admin, sentinelrag, "Manages tenant config", "HTTPS")
    Rel(eval_engineer, sentinelrag, "Runs evals, edits prompts", "HTTPS / SDK")
    Rel(sre, sentinelrag, "Reads telemetry; runs game-day", "kubectl, Grafana, Chaos Mesh CRDs")

    Rel(sentinelrag, idp,           "Verifies JWTs (JWKS)",        "HTTPS")
    Rel(sentinelrag, llm_apis,      "Generation + embedding",      "HTTPS via LiteLLM")
    Rel(sentinelrag, object_store,  "Reads docs; writes audit",    "S3 API / GCS API")
    Rel(sentinelrag, observability, "Emits OTLP",                  "gRPC")
    Rel(sentinelrag, flags,         "Reads feature flags",         "HTTPS")
    Rel(sentinelrag, secrets,       "Pulls runtime secrets via ESO","HTTPS")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

## Key rules visible at this level

- **End-to-end identity flow.** Every user request carries a Keycloak JWT; the `tenant_id` claim binds the request to a Postgres RLS context.
- **Audit dual-write reaches outside the box.** Object storage with Object Lock is part of the perimeter — it's how immutability is enforced (ADR-0016).
- **LLM calls are external dependencies, not in-process.** Routed through a single LiteLLM gateway so cost accounting is uniform regardless of provider (ADR-0005).

## Related ADRs

- [ADR-0008](../adr/0008-keycloak-auth.md) — Keycloak self-hosted
- [ADR-0014](../adr/0014-hybrid-llm-strategy.md) — Hybrid LLM strategy (Ollama default, OpenAI / Anthropic opt-in)
- [ADR-0016](../adr/0016-immutable-audit-dual-write.md) — Audit dual-write
- [ADR-0018](../adr/0018-feature-flags-unleash.md) — Unleash for feature flags
