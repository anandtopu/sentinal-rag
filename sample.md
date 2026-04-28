# SentinelRAG demo document

SentinelRAG is a multi-tenant retrieval-augmented generation platform.
It enforces RBAC at retrieval time using Postgres row-level security and
hybrid search that combines BM25 (Postgres FTS) with HNSW vector indexes
on pgvector. Every answer is traceable: the query session id joins
retrieval results, the generated answer, and citations to source chunks.

The grounding score is computed by token overlap between the answer and
the retrieved context, then optionally cross-checked with an NLI model.
LLM calls flow through a LiteLLM gateway with per-tenant cost budgets.
