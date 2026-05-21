"""VectorSearch protocol + pgvector HNSW implementation.

Per ADR-0020, embeddings live in three per-dimension columns
(``embedding_768``, ``embedding_1024``, ``embedding_1536``). The
:class:`PgvectorVectorSearch` adapter dispatches on the embedder's
``dimension`` to query the matching column + HNSW index.

The query embedding is computed inside this class via the supplied
:class:`Embedder`; the caller passes the model alias and we resolve dim
from ``EMBEDDER_DIMENSIONS``. Two different collections in the same
tenant CAN use different embedders — the per-dim column design supports
this cleanly; cross-dim retrieval is intentionally impossible.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.llm import Embedder
from sentinelrag_shared.retrieval.access_filter import AccessFilter
from sentinelrag_shared.retrieval.candidate import Candidate, RetrievalStage


class VectorSearchError(Exception):
    """Raised on unsupported dim or query failure."""


# Map dimension → (column name, HNSW index name).
_DIM_TO_COLUMN: dict[int, str] = {
    768: "embedding_768",
    1024: "embedding_1024",
    1536: "embedding_1536",
}


class VectorSearch(Protocol):
    """Protocol for dense-vector retrieval."""

    async def search(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID] | None,
        top_k: int,
        ef_search: int | None = None,
    ) -> list[Candidate]: ...


class PgvectorVectorSearch:
    """pgvector HNSW search dispatching on embedder dimension.

    Args:
        session: tenant-bound AsyncSession (RLS active).
        embedder: produces the query vector. The embedder's ``model_name``
            MUST match an ``embedding_model`` value present in
            ``chunk_embeddings`` for any chunk to be returned.
        access_filter: shared instance recommended.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedder: Embedder,
        access_filter: AccessFilter | None = None,
    ) -> None:
        self.session = session
        self.embedder = embedder
        self.access_filter = access_filter or AccessFilter()
        if embedder.dimension not in _DIM_TO_COLUMN:
            msg = (
                f"Unsupported embedding dim {embedder.dimension} for {embedder.model_name!r}. "
                "Supported dims (per ADR-0020): 768, 1024, 1536."
            )
            raise VectorSearchError(msg)

    async def search(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID] | None,
        top_k: int,
        ef_search: int | None = None,
    ) -> list[Candidate]:
        if not query.strip() or top_k <= 0:
            return []

        embedding = await self.embedder.embed([query])
        if not embedding.vectors:
            return []
        query_vec = embedding.vectors[0]
        column = _DIM_TO_COLUMN[self.embedder.dimension]

        predicate = self.access_filter.build(auth=auth, collection_ids=collection_ids)

        # ef_search controls HNSW recall/latency. Set per-query via SET LOCAL
        # so it doesn't leak. Default 40 is pgvector's recommended value.
        if ef_search is not None:
            await self.session.execute(
                text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
            )

        # We want the cosine *similarity* (higher = better) but pgvector's
        # ``<=>`` returns *distance* (lower = better). Convert with 1 - dist.
        # S608: ``column`` comes from a fixed dim→column mapping; predicate
        # parts are internally generated. No user input is interpolated.
        sql = f"""
            {predicate.cte_sql}
            SELECT
                chunks.id,
                chunks.document_id,
                chunks.content,
                chunks.page_number,
                chunks.section_title,
                1 - (ce.{column} <=> CAST(:query_vec AS vector)) AS score
            FROM chunk_embeddings ce
            JOIN document_chunks chunks ON chunks.id = ce.chunk_id
            WHERE ce.embedding_model = :embedding_model
              AND ce.{column} IS NOT NULL
              AND {predicate.sql}
            ORDER BY ce.{column} <=> CAST(:query_vec AS vector) ASC
            LIMIT :top_k
        """  # noqa: S608

        result = await self.session.execute(
            text(sql),
            {
                **predicate.params,
                "embedding_model": self.embedder.model_name,
                "query_vec": _format_vector(query_vec),
                "top_k": top_k,
            },
        )
        rows = result.fetchall()

        return [
            Candidate(
                chunk_id=row.id,
                document_id=row.document_id,
                content=row.content,
                score=float(row.score or 0.0),
                rank=rank,
                stage=RetrievalStage.VECTOR,
                page_number=row.page_number,
                section_title=row.section_title,
            )
            for rank, row in enumerate(rows, start=1)
        ]


def _format_vector(vec: list[float]) -> str:
    """Format a Python list as a pgvector literal: '[v1,v2,...]'."""
    return "[" + ",".join(str(float(x)) for x in vec) + "]"
