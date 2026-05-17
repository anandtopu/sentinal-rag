# ADR-0036: Vector sharding and per-tenant pgvector index strategy

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** retrieval, pgvector, scale, multi-tenancy

## Context

[ADR-0003](0003-pgvector-hnsw.md) commits to pgvector HNSW indexes
over the `chunk_embeddings` table. Today every tenant's vectors live
in the same HNSW graph, filtered at query time by the RLS / app-level
`tenant_id` predicate.

This works well for small/medium tenants. It does not necessarily
scale. Two failure modes show up in pgvector benchmarks past ~5M
vectors per index:

1. **Recall drift.** HNSW recall is a function of `ef_search` and the
   graph's neighbor density. A shared index across many tenants
   means a single tenant's "top-k closest" may sit deep in the graph
   behind unrelated neighbors. Recall@k drops measurably when one
   tenant's corpus exceeds ~50% of the graph's neighbor population.
2. **Index maintenance cost.** HNSW build time + memory footprint
   grow roughly linearly with corpus size. A single rebuild of a
   30M-vector shared index blocks writes for tens of minutes; this
   is a Postgres-side operational liability.

A senior reviewer will probe "what happens when a customer onboards
20M chunks?" We need an answer before the demo, and a path before the
first big customer.

The constraints:

- [ADR-0033](0033-zero-downtime-schema-migrations.md) makes schema
  shape moves possible without downtime, but per-tenant *tables* are
  a steep multiplier — we'd give up the "one schema, many tenants"
  property that RLS hinges on.
- The 768/1024/1536-dim columns from
  [ADR-0020](0020-multi-dim-embeddings.md) already partition the
  table by dimension. We can layer further partitioning on top.
- Postgres 16's declarative partitioning + pgvector HNSW *do* compose,
  but only on `LIST` / `RANGE` partitioning; HNSW indexes are
  per-partition, not global.

## Decision

**Shared HNSW index by default; carve a per-tenant index out only when
the tenant crosses a documented threshold and the carve-out is
benchmarked to win on recall@k.** No partitioning until the carve-out
fires.

### Default mode

- One HNSW index per embedding dimension column
  (`embedding_768`, `embedding_1024`, `embedding_1536`), shared
  across every tenant. This is what ships today.
- The retrieval-side filter (RLS + app-level `tenant_id` predicate
  from [ADR-0004](0004-postgres-fts-over-opensearch.md)) is applied
  during the scan; pgvector evaluates the HNSW neighborhood then
  drops rows that don't pass the predicate.
- This is **correct** for any tenant size; it's the *performance*
  characteristics that change at scale.

### Carve-out triggers

A tenant becomes a carve-out candidate when **any** of:

| Trigger | Threshold | How measured |
|---|---|---|
| Chunks | > 5,000,000 chunks in that tenant | `SELECT COUNT(*) FROM document_chunks WHERE tenant_id = $1` |
| Share of shared index | > 25% of total chunks in the shared graph | per-tenant count vs `SELECT COUNT(*)` global |
| Recall regression | Measured recall@10 < 0.85 against the eval set for that tenant's queries | The eval harness from [ADR-0019](0019-evaluation-framework-ragas.md) reports per-tenant recall as part of every run |

A nightly job (Temporal) walks the per-tenant chunk counts and emits
a structured warning when any trigger fires. The warning surfaces in
the admin dashboard + Slack; carve-out is operator-initiated, not
automatic — we don't want a runaway tenant to silently spawn shadow
indexes.

### Carve-out mechanism

When a carve-out is initiated for tenant T:

1. **Expand step (class B per ADR-0033):** create a partial HNSW
   index on `chunk_embeddings` `WHERE tenant_id = T`:
   ```sql
   CREATE INDEX CONCURRENTLY idx_chunk_embeddings_768_tenant_$T_hnsw
     ON chunk_embeddings USING hnsw (embedding_768 vector_cosine_ops)
     WHERE tenant_id = $T;
   ```
   Postgres' planner picks the partial index automatically when the
   query's `tenant_id` predicate matches.
2. **Verify:** rerun the eval harness for tenant T; confirm recall@10
   passes threshold.
3. **No-op for the app:** retrieval code is unchanged — the planner
   handles index selection. No new SQL path; no new contract.
4. **Tear-down** (class B' per ADR-0033): if a tenant shrinks
   below threshold, the partial index is droppable in a single
   `DROP INDEX CONCURRENTLY`.

### What we explicitly DON'T do

- **No per-tenant tables.** Breaks the RLS model + the `documents JOIN
  chunks` query shape; doubles the migration surface for every
  schema change.
- **No declarative partitioning by `tenant_id`** at the
  `chunk_embeddings` level — for the same reason. Partitioning by
  dimension stays (ADR-0020); partitioning by tenant on top adds
  no benefit our partial-index approach doesn't already give.
- **No automatic carve-out trigger.** The detection job emits a
  warning; an operator runs the carve-out from the admin runbook.
  This keeps schema drift visible and reversible.
- **No quantization or HNSW tuning beyond ef_search.** That's a
  separate retrieval-quality ADR if it ever lands; today we get
  enough headroom from the partial-index pattern.

### What the runbook covers

`docs/operations/runbooks/vector-carveout.md` (implementation
phase) ships with:

1. The exact `CREATE INDEX CONCURRENTLY` statement template.
2. The eval-harness command to verify recall@10 pre- and
   post-carve-out.
3. Disk-space budgeting (HNSW index ≈ corpus-size × 1.2 for the
   default `m=16` build parameters).
4. The rollback procedure (`DROP INDEX CONCURRENTLY`).

## Consequences

### Positive

- v1 ships with a clean default — one index per dim, RLS-filtered.
  No premature complexity.
- The carve-out path is well-trodden Postgres territory — partial
  indexes have been there forever. The HNSW twist is small.
- Per-tenant *indexes* (not tables) keep the RLS + schema model
  intact. The shared schema is still single-source-of-truth.
- The detection job + admin-initiated trigger gives operators the
  signal without surprising them with a runaway DDL operation.

### Negative

- A growing number of carve-outs means a growing number of partial
  indexes. At 50+ large tenants this is real disk pressure and a
  per-DML cost (each `INSERT` updates every relevant partial index).
  Mitigation: at 10+ carve-outs, revisit per-tenant partitioning
  with the benchmark data we'll have by then.
- The recall-regression trigger requires a per-tenant eval set
  good enough to measure recall meaningfully. ADR-0019's eval
  framework supports this, but populating per-tenant eval data is
  a real customer-onboarding task.
- Operator-initiated carve-out adds operational toil. A future ADR
  may automate this once we trust the trigger heuristics.

### Neutral

- Postgres' query planner sometimes prefers the shared index over
  a partial index when the predicate isn't perfectly aligned
  (e.g. an additional `created_at` filter on the query). We document
  the `EXPLAIN ANALYZE` check in the runbook.

## Alternatives considered

### Option A — Partial per-tenant HNSW indexes (this)
- See above.

### Option B — Per-tenant table inheritance / partitioning
- **Pros:** Mechanically separates tenant data; each partition has
  its own HNSW index with no shared graph contention.
- **Cons:** Breaks RLS (we'd need to push tenant_id into the
  partition key + audit every cross-tenant query); every schema
  change has to fan out across N partitions; partition pruning
  must be perfect or queries scan everything.
- **Rejected because:** the operational + schema cost dwarfs the
  performance gain at v1 + v2 scale. Revisit at 50+ carve-out
  candidates.

### Option C — Move large tenants to a dedicated Postgres instance
- **Pros:** Full isolation; truly independent scaling.
- **Cons:** Cross-instance joins (audit, usage, prompts) become
  application-side joins; multi-cluster ops; defeats the
  single-Postgres simplicity that AGENTS.md emphasizes.
- **Rejected because:** disproportionate cost. The HNSW partial-
  index pattern handles the same recall concern without splitting
  the storage tier.

### Option D — Quantization (PQ / IVF) instead of HNSW
- **Pros:** Lower memory; supports billions of vectors per index.
- **Cons:** Recall trade-off (typical −5–15% at the cost of −80%
  memory). ADR-0003 already evaluated pgvector HNSW vs IVF and
  picked HNSW for our scale.
- **Rejected because:** ADR-0003's reasoning still holds; we're
  not at the scale that justifies PQ.

## Trade-off summary

| Dimension | Partial index (this) | Per-tenant table | Dedicated instance | Quantization |
|---|---|---|---|---|
| Recall at scale | Good (per partial graph) | Best | Best | Lower |
| Operational cost | Low (one DDL per carve-out) | High (schema fan-out) | Very high | Low |
| Disk per large tenant | +1× corpus | +0× (already separate) | +1× corpus on dedicated DB | −80% |
| Code change required | None (planner handles it) | High | High | Medium |
| Multi-cluster Postgres ops | 0 | 0 | Yes | 0 |
| Reversibility | `DROP INDEX CONCURRENTLY` | Hard | Hard | Hard |

## Notes on the design docs

The Database Design doc does NOT specify per-tenant index strategy.
ADR-0020 + ADR-0003 establish the column shape. This ADR fills the
"what about at scale" gap.

The Helm chart's `templates/migrations/job.yaml` is unchanged — the
carve-out DDL runs out-of-band from a normal release (it's not part
of `alembic upgrade head`); it lives in
`docs/operations/runbooks/vector-carveout.md` for an operator to run
when the detection job fires.

## References

- [ADR-0003](0003-pgvector-hnsw.md) — pgvector HNSW base decision
- [ADR-0019](0019-evaluation-framework-ragas.md) — the recall-
  measurement seam used by the carve-out trigger
- [ADR-0020](0020-multi-dim-embeddings.md) — per-dimension column
  layout, the partitioning that already exists
- [ADR-0033](0033-zero-downtime-schema-migrations.md) — class-B/B'
  pattern for carve-out / tear-down
- [pgvector HNSW reference](https://github.com/pgvector/pgvector#hnsw)
  — index parameters
- [Postgres partial indexes](https://www.postgresql.org/docs/16/indexes-partial.html)
- [Malkov & Yashunin — HNSW](https://arxiv.org/abs/1603.09320)
