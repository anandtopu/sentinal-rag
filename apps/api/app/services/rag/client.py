"""RetrievalClient — the seam between the orchestrator and retrieval backend.

R1.S1 ships only ``InProcessRetrievalClient``, which composes
``PostgresFtsKeywordSearch`` + ``PgvectorVectorSearch`` + ``HybridRetriever``
from the shared library. R4 adds ``HttpRetrievalClient`` (network-bound
call to ``apps/retrieval-service``) behind this same Protocol — that's
why the orchestrator depends on the abstraction from day one.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.llm import LiteLLMEmbedder
from sentinelrag_shared.retrieval import (
    AccessFilter,
    HybridRetrievalResult,
    HybridRetriever,
    PgvectorVectorSearch,
    PostgresFtsKeywordSearch,
    RetrievalStage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag._helpers import restage_candidates


class RetrievalClient(Protocol):
    """Async contract a RAG retrieval backend must satisfy.

    ``mode`` is one of ``"bm25"``, ``"vector"``, or ``"hybrid"``. The
    implementation dispatches to the right backend(s) and returns the unified
    ``HybridRetrievalResult`` shape so the orchestrator persists the same
    stage-tagged rows regardless of mode.
    """

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        mode: str,
        top_k_bm25: int,
        top_k_vector: int,
        top_k_hybrid: int,
        ef_search: int | None,
    ) -> HybridRetrievalResult: ...


class InProcessRetrievalClient:
    """In-process implementation — calls the shared retrieval library directly.

    Per-request construction is preserved here to match v1 behavior; R3.S6
    hoists embedder + session to ``app.state`` and DIs them in.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedder: LiteLLMEmbedder,
        access_filter: AccessFilter | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._access_filter = access_filter or AccessFilter()

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        mode: str,
        top_k_bm25: int,
        top_k_vector: int,
        top_k_hybrid: int,
        ef_search: int | None,
    ) -> HybridRetrievalResult:
        keyword_search = PostgresFtsKeywordSearch(
            session=self._session, access_filter=self._access_filter
        )
        vector_search = PgvectorVectorSearch(
            session=self._session,
            embedder=self._embedder,
            access_filter=self._access_filter,
        )

        if mode == "bm25":
            bm25 = await keyword_search.search(
                query=query,
                auth=auth,
                collection_ids=collection_ids,
                top_k=top_k_bm25,
            )
            return HybridRetrievalResult(
                bm25_candidates=bm25,
                vector_candidates=[],
                merged_candidates=restage_candidates(
                    bm25[:top_k_hybrid], RetrievalStage.HYBRID_MERGE
                ),
            )

        if mode == "vector":
            vector = await vector_search.search(
                query=query,
                auth=auth,
                collection_ids=collection_ids,
                top_k=top_k_vector,
                ef_search=ef_search,
            )
            return HybridRetrievalResult(
                bm25_candidates=[],
                vector_candidates=vector,
                merged_candidates=restage_candidates(
                    vector[:top_k_hybrid], RetrievalStage.HYBRID_MERGE
                ),
            )

        hybrid = HybridRetriever(
            keyword_search=keyword_search,
            vector_search=vector_search,
        )
        return await hybrid.retrieve(
            query=query,
            auth=auth,
            collection_ids=collection_ids,
            top_k_bm25=top_k_bm25,
            top_k_vector=top_k_vector,
            top_k_hybrid=top_k_hybrid,
            ef_search=ef_search,
        )
