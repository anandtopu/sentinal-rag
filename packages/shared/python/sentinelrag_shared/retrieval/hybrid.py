"""HybridRetriever — BM25 + vector with reciprocal rank fusion + dedupe.

Reciprocal Rank Fusion (RRF) is robust and parameter-light:

    rrf_score(d) = sum_i  1 / (k + rank_i(d))

with ``k=60`` recommended by Cormack/Lynam (2009). The constant smooths
extreme ranks; we don't tune per-query in v1.

Output ordering: by RRF score, descending. Each output Candidate carries
the BM25 + vector ranks in metadata so the trace UI can show which path
contributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.retrieval.candidate import Candidate, RetrievalStage
from sentinelrag_shared.retrieval.keyword_search import KeywordSearch
from sentinelrag_shared.retrieval.vector_search import VectorSearch


@dataclass(slots=True)
class HybridRetrievalResult:
    """Bundle returned by HybridRetriever.

    Carries each stage's raw results so the orchestrator can persist them
    to ``retrieval_results`` for the query trace.
    """

    bm25_candidates: list[Candidate]
    vector_candidates: list[Candidate]
    merged_candidates: list[Candidate]
    metadata: dict[str, Any] = field(default_factory=dict)


class HybridRetriever:
    """Run BM25 + vector in parallel and merge with RRF.

    Args:
        keyword_search: KeywordSearch implementation.
        vector_search:  VectorSearch implementation.
        rrf_k:          RRF constant. 60 is the standard.
    """

    def __init__(
        self,
        *,
        keyword_search: KeywordSearch,
        vector_search: VectorSearch,
        rrf_k: int = 60,
    ) -> None:
        self.keyword_search = keyword_search
        self.vector_search = vector_search
        self.rrf_k = rrf_k

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID] | None,
        top_k_bm25: int = 20,
        top_k_vector: int = 20,
        top_k_hybrid: int = 30,
        ef_search: int | None = None,
    ) -> HybridRetrievalResult:
        """Run both arms; merge; return up to ``top_k_hybrid`` candidates.

        Note: in v1 we run sequentially; ``asyncio.gather`` is the obvious
        next step but each arm's session is the same SQLAlchemy session,
        which is NOT safe for concurrent use. To parallelize we'd need two
        sessions — deferred until benchmarks justify it.
        """
        bm25 = await self.keyword_search.search(
            query=query,
            auth=auth,
            collection_ids=collection_ids,
            top_k=top_k_bm25,
        )
        vector = await self.vector_search.search(
            query=query,
            auth=auth,
            collection_ids=collection_ids,
            top_k=top_k_vector,
            ef_search=ef_search,
        )

        merged = self._rrf_merge(bm25, vector, top_k_hybrid)

        return HybridRetrievalResult(
            bm25_candidates=bm25,
            vector_candidates=vector,
            merged_candidates=merged,
            metadata={
                "rrf_k": self.rrf_k,
                "bm25_returned": len(bm25),
                "vector_returned": len(vector),
                "merged_returned": len(merged),
            },
        )

    def _rrf_merge(
        self,
        bm25: list[Candidate],
        vector: list[Candidate],
        top_k: int,
    ) -> list[Candidate]:
        """Combine two ranked lists via Reciprocal Rank Fusion + dedupe."""
        scored: dict[UUID, tuple[float, Candidate, int | None, int | None]] = {}

        for cand in bm25:
            rrf = 1.0 / (self.rrf_k + cand.rank)
            scored[cand.chunk_id] = (rrf, cand, cand.rank, None)

        for cand in vector:
            rrf = 1.0 / (self.rrf_k + cand.rank)
            if cand.chunk_id in scored:
                prev_score, prev_cand, prev_bm25_rank, _ = scored[cand.chunk_id]
                # Prefer the BM25-fetched cand for content/metadata (FTS includes
                # page_number etc. consistently); attach vector_rank.
                scored[cand.chunk_id] = (
                    prev_score + rrf,
                    prev_cand,
                    prev_bm25_rank,
                    cand.rank,
                )
            else:
                scored[cand.chunk_id] = (rrf, cand, None, cand.rank)

        ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        out: list[Candidate] = []
        for new_rank, (rrf_score, cand, bm25_rank, vector_rank) in enumerate(
            ranked[:top_k], start=1
        ):
            out.append(
                Candidate(
                    chunk_id=cand.chunk_id,
                    document_id=cand.document_id,
                    content=cand.content,
                    score=rrf_score,
                    rank=new_rank,
                    stage=RetrievalStage.HYBRID_MERGE,
                    page_number=cand.page_number,
                    section_title=cand.section_title,
                    metadata={
                        "bm25_rank": bm25_rank,
                        "vector_rank": vector_rank,
                    },
                )
            )
        return out
