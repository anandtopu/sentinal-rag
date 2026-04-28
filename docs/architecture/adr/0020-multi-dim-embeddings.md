# ADR-0020: Multi-dimension embeddings via per-dimension columns

- **Status:** Accepted
- **Date:** 2026-04-26
- **Tags:** schema, pgvector, embeddings, retrieval

## Context

ADR-0014 (Hybrid LLM strategy) commits to **`nomic-embed-text` (768d)** as the self-hosted default embedding model and **`text-embedding-3-small` (1536d)** as the cloud opt-in. Migration `0004_documents` was written before ADR-0014 was finalized and hardcoded `chunk_embeddings.embedding vector(1536) NOT NULL` — mismatched with the 768d default.

pgvector's `vector(N)` type fixes the dimension at column-creation time. The `vector` type itself does not support variable dimensions; you must commit to a dim per column.

Three ways to support multiple embedding dimensions:

1. **Per-dimension columns** on a single `chunk_embeddings` table (with a CHECK that exactly one is non-NULL).
2. **Per-dimension tables** (`chunk_embeddings_768`, `chunk_embeddings_1536`).
3. **Single dim system-wide** — pick one (e.g. project nomic-embed to 1536 via padding/MRL projection) and live with it.

Per-collection dim binding (each collection's chunks all use the same embedder) is independent of these and applies to all three.

## Decision

**Per-dimension columns** on `chunk_embeddings`:

```sql
embedding_768   vector(768)   NULL,
embedding_1024  vector(1024)  NULL,
embedding_1536  vector(1536)  NULL,
CHECK (
    (embedding_768 IS NOT NULL)::int +
    (embedding_1024 IS NOT NULL)::int +
    (embedding_1536 IS NOT NULL)::int = 1
)
```

One HNSW index per non-NULL dim column. The retrieval-service's `VectorSearch` adapter dispatches to the right column based on the embedder's `dimension` property:

```python
match embedder.dimension:
    case 768:  use embedding_768
    case 1024: use embedding_1024
    case 1536: use embedding_1536
    case _:    raise UnsupportedDimensionError
```

We support exactly three dims in v1: **768, 1024, 1536** — covers nomic-embed-text (768), bge-large-en-v1.5 / mxbai-embed-large (1024), text-embedding-3-small (1536). Additional dims require a new migration adding the column + index.

## Consequences

### Positive

- Schema cleanly supports the v1 default + opt-in embedders without runtime branching beyond the dispatch.
- Adding a fourth dim is a small, reviewable migration (one column + one index).
- HNSW index on the actually-populated column → no wasted index work.
- Per-collection dim binding stays simple: `collections.metadata.embedding_dim` is the source of truth at retrieval time.

### Negative

- Three index slots × ~12GB/M-vectors at 1536d → larger Postgres footprint *if* a tenant uses all three dims simultaneously. In practice each collection picks one dim and only that column's index grows.
- The dispatch logic lives in retrieval-service — tested in unit tests, but a real ergonomics cost.
- ALTER TABLE on a populated chunk_embeddings table to add new dims later requires careful rollout (dim columns are NULLABLE so the table-rewrite is fast, but the new HNSW index build on existing rows is the slow part).

### Neutral

- Per-tenant choice of dim is reflected in `chunk_embeddings.embedding_model` (text label) — the human-readable record stays correct.

## Alternatives considered

### Option A — Per-dimension tables
- **Pros:** Each table has only the columns it needs. Cleaner separation.
- **Cons:** N tables to migrate, query, partition. Cross-dim joins become awkward. Repository layer multiplies.
- **Rejected because:** Adding a dim becomes a new table, not a new column — bigger blast radius.

### Option B — Project all embeddings to a single dim (e.g. 1536d via MRL or zero-padding)
- **Pros:** Single column. No dispatch.
- **Cons:** Zero-padding wastes storage AND distorts cosine similarity at retrieval time. Matryoshka projection is model-specific and adds inference-time complexity. Loses fidelity vs. native dim.
- **Rejected because:** Quality regression for storage convenience is the wrong trade-off.

### Option C — Switch self-hosted default to a 1536d model
- **Pros:** Schema stays exactly as in 0004.
- **Cons:** Few well-known open-source 1536d embedders exist. The ones that do (e.g. e5-mistral-7b-instruct at 4096d truncated) are 7B+ params and require a non-trivial GPU footprint just for embeddings — conflicts with the lean self-hosted demo story.
- **Rejected because:** Forces a model choice driven by schema convenience instead of quality/cost.

## Trade-off summary

| Dimension | Per-dim columns | Per-dim tables | Single-dim projection |
|---|---|---|---|
| New-dim cost | 1 migration (column + index) | 1 new table + repo + index | none |
| Query complexity | Dispatch on `dimension` | Dispatch on table name | None |
| Storage at scale | Three index slots; only populated ones grow | N tables, only populated ones grow | One index, full size |
| Quality | Native | Native | Degraded (projection) |

## Notes on the design docs

**Overrides** `Enterprise_RAG_Database_Design.md` §5.4 (the single `embedding vector(1536)` column). Migration `0011_multi_dim_embeddings.py` performs the schema change.

**Aligns with** ADR-0014 — the `nomic-embed-text` (768d) default is now schema-supported.

## References

- [pgvector storage](https://github.com/pgvector/pgvector#storing)
- [Matryoshka Representation Learning](https://arxiv.org/abs/2205.13147) — relevant for nomic-embed-text-v1.5
