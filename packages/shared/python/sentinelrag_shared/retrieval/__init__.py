"""Retrieval primitives (in-process v1; extracted to retrieval-service in Phase 7 — ADR-0021).

Hierarchy:
    AccessFilter      — RBAC predicate builder, applied at query time.
    KeywordSearch     — protocol; PostgresFtsKeywordSearch is the v1 impl.
    VectorSearch      — protocol; PgvectorVectorSearch is the v1 impl.
    HybridRetriever   — combines the two with reciprocal rank fusion + dedupe.
    Candidate         — the unit of retrieval output (chunk_id, score, stage).

Architectural pillar (CLAUDE.md): RBAC at retrieval time, NOT post-mask. The
AccessFilter is applied to BOTH BM25 and vector queries before candidates are
fetched — unauthorized chunks never enter the rerank/generation path.
"""

from sentinelrag_shared.retrieval.access_filter import AccessFilter, AccessFilterPredicate
from sentinelrag_shared.retrieval.candidate import Candidate, RetrievalStage
from sentinelrag_shared.retrieval.hybrid import (
    HybridRetrievalResult,
    HybridRetriever,
    merge_with_rrf,
)
from sentinelrag_shared.retrieval.keyword_search import (
    KeywordSearch,
    PostgresFtsKeywordSearch,
)
from sentinelrag_shared.retrieval.vector_search import (
    PgvectorVectorSearch,
    VectorSearch,
)

__all__ = [
    "AccessFilter",
    "AccessFilterPredicate",
    "Candidate",
    "HybridRetrievalResult",
    "HybridRetriever",
    "KeywordSearch",
    "PgvectorVectorSearch",
    "PostgresFtsKeywordSearch",
    "RetrievalStage",
    "VectorSearch",
    "merge_with_rrf",
]
