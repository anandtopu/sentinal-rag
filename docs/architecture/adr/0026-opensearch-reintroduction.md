# ADR-0026: OpenSearch reintroduction — second adapter behind the existing KeywordSearch protocol; RBAC enforced via Postgres-resolved collection filter

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** retrieval, search, multi-cloud, rbac

## Context

ADR-0004 deferred OpenSearch and shipped Postgres FTS as the v1 BM25 backend.
The deferral was deliberate so we could prove the abstraction (the
`KeywordSearch` protocol) and *measure* the migration when scale or
fidelity demanded it. Phase 8 reintroduces OpenSearch — but only as a
parallel adapter, A/B-able against Postgres FTS rather than a replacement.

Three problems came up the moment OpenSearch left the diagram and
hit the keyboard:

1. **OpenSearch is outside the Postgres RLS perimeter.** Tenant isolation
   and per-collection authorization can't ride on the session-bound
   `app.current_tenant_id` setting. We need an explicit RBAC filter
   strategy.
2. **Indexing pipeline.** Postgres FTS indexed on a generated column
   trigger — chunk insert ⇒ chunk searchable, transactionally consistent.
   OpenSearch is a second store; we have to choose between (a) dual-write
   from the ingestion activity, (b) Debezium-style CDC, (c) periodic batch
   indexer. Each has different failure modes.
3. **Drift detection.** If OpenSearch is the production keyword backend
   but loses a document during an outage, we need to know.

## Decision

### Plug behind the existing protocol — no API surface change

`OpenSearchKeywordSearch` implements the same `KeywordSearch` protocol as
`PostgresFtsKeywordSearch`. The orchestrator picks one or the other via
DI at startup; nothing in `RagOrchestrator` or `HybridRetriever` changes.
This is the payoff for ADR-0004's interface discipline.

A feature flag (`unleash`: `keyword_backend=opensearch|postgres`) selects
the adapter per request, so an A/B can run against live traffic.

### RBAC via Postgres-resolved collection filter

At query time:

1. The adapter calls Postgres with the same `authorized_collections` CTE
   the `AccessFilter` already builds. **One round-trip** to resolve the set
   of collection IDs the user can read.
2. The OpenSearch query carries:
   - `term: tenant_id = <auth.tenant_id>` (defense in depth — bug here would
     leak across tenants).
   - `terms: collection_id ∈ <authorized_collections>` (per-collection
     authorization).
3. Caller-requested `collection_ids` further narrows the `terms` filter.

**Postgres remains the single source of truth for RBAC.** OpenSearch only
gets a constant-time list-membership check. If the role/collection_access
graph changes, the next query reflects it. There is no second authorization
store to keep consistent.

### Indexing: dual-write from the Temporal ingestion activity

A new activity `index_chunks_to_opensearch` runs after the existing
`embed_chunks_and_persist` activity in `IngestionWorkflow`. It pulls the
freshly-persisted chunks + their `documents` row and `bulk_index`es them
into OpenSearch with the denormalized shape:

```python
{
  "chunk_id":       <uuid>,
  "document_id":    <uuid>,
  "tenant_id":      <uuid>,
  "collection_id":  <uuid>,
  "content":        <chunk text>,
  "page_number":    <int|null>,
  "section_title":  <string|null>,
}
```

Activity is **idempotent** (`_id = chunk_id` so re-runs upsert), so
Temporal's at-least-once semantics work without duplicate-detection logic.

When a document version is superseded, the corresponding evictor activity
calls `delete_by_document(tenant_id, document_id)` to drop old chunks.

Dual-write was picked over CDC because:
- **Debezium adds a queue + connector to operate.** Real cost; we already
  have Temporal as the durable runtime.
- **Activity granularity matches workflow semantics.** A failure in the
  index step doesn't roll back the whole ingestion; Temporal retries the
  activity until it succeeds, with backoff.
- **The drift bound is one activity retry window**, observable via Temporal
  history.

### Drift detection — `audit_reconciliation`-style daily diff

A new daily Temporal Schedule runs `OpenSearchDriftReconciliation`:

1. Sample N chunks per tenant per day.
2. Confirm each appears in OpenSearch (`exists` + tenant_id/collection_id
   filter).
3. Emit `sentinelrag_opensearch_drift_total{side="missing-from-os"}` and
   `{side="missing-from-pg"}` OTel metrics.

Same reconciliation pattern as the audit dual-write (Phase 6.5). Reuses
the orchestration helpers in `sentinelrag_shared.audit.reconciliation`.

(Implementation lands when the OpenSearch adapter is wired to a live
domain; the unit tests for the diff math can be authored against the
existing reconciliation helpers without infra.)

### What we did NOT do

- **No write-back from OpenSearch to Postgres.** OpenSearch is a derived
  index, never the source of truth.
- **No global merge of OpenSearch + Postgres FTS at query time.** They are
  alternatives, picked by feature flag. Mixing produces hybrid scores
  that are hard to reason about.
- **No fine-grained-access-control via OpenSearch's built-in roles**
  beyond the master user. Document-level ACLs in OpenSearch's roles are a
  trap — keep the policy graph in one store (Postgres).

## Consequences

### Positive

- Same protocol, same call sites, two backends. The migration story
  becomes "flip a flag in Unleash, watch the eval scores, stick or
  revert" — measured, reversible.
- Postgres remains the RBAC source of truth. We are not synchronizing two
  policy graphs.
- The dual-write pattern reuses the audit-reconciliation skeleton —
  one well-understood operational shape, applied to a new pair of stores.

### Negative

- We now operate two stores. ~$300+/mo idle cost on AWS managed
  OpenSearch (deferred ADR-0004 cost, now incurred).
- Index drift is a real failure mode that needs the reconciliation job to
  catch. Until that ships, drift would be silent.
- A query at retrieval time costs one Postgres round-trip even when only
  OpenSearch is consulted (to resolve authorized collections). Mitigated
  by Postgres caching the CTE plan; the round-trip is sub-millisecond on
  a properly-tuned RDS.

### Neutral

- The `KeywordSearch` protocol's signature didn't change.
- The Postgres FTS adapter remains in production as the fallback.

## Alternatives considered

### Option A — Replace Postgres FTS entirely
- **Pros:** One backend.
- **Cons:** Loses the eval data showing OpenSearch wins for specific
  query shapes; eliminates a useful baseline.
- **Rejected because:** the comparison itself is the recruiter signal.

### Option B — Sync OpenSearch from Postgres via Debezium CDC
- **Pros:** Decouples ingestion from indexing.
- **Cons:** New runtime (Debezium + Kafka or Kafka Connect alternative).
  Operational footprint.
- **Rejected because:** dual-write through Temporal activities is enough
  at our scale, and we already operate Temporal.

### Option C — Token-level role filter inside OpenSearch (FGAC)
- **Pros:** Native OpenSearch feature.
- **Cons:** Two policy graphs to keep in sync. Operator footgun.
- **Rejected because:** Postgres is the source of truth for RBAC; we
  don't fork it.

## Trade-off summary

| Dimension | OpenSearch-as-second-adapter (this) | Replace Postgres FTS | Debezium CDC |
|---|---|---|---|
| Stores in prod | 2 | 1 | 2 + Kafka |
| Source of truth (RBAC) | Postgres | Postgres | Postgres |
| Indexing latency | activity SLA (~seconds) | trigger-time (instant) | CDC lag (~seconds) |
| Drift detection | daily reconciliation | n/a | n/a (CDC is "always") |
| Reversibility | flip the flag | redeploy | rebuild pipeline |
| Operational cost | $$ | $ | $$$ |

## Notes on the design docs

`Enterprise_RAG_PRD.md` §6.3 originally specified OpenSearch from day one;
ADR-0004 deferred. This ADR is the deferred-then-reintroduced shape, with
RBAC and drift discipline added.

## References

- ADR-0004: Postgres FTS for v1 BM25; OpenSearch deferred
- ADR-0008: Keycloak self-hosted for OAuth2/JWT
- ADR-0016: Audit dual-write (the reconciliation pattern reused here)
- ADR-0021: Retrieval embedded in-process for v1
