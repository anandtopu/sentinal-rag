"""RerankStage — bge / no-op reranker + persist the rerank-stage rows."""

from __future__ import annotations

from sentinelrag_shared.llm import RerankCandidate, Reranker, RerankerError
from sentinelrag_shared.retrieval import Candidate
from sentinelrag_shared.retrieval import RetrievalStage as RetrievalStageEnum
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import RetrievalResultRepository
from app.services.rag.types import QueryContext


class RerankStage:
    def __init__(self, session: AsyncSession, reranker: Reranker) -> None:
        self._session = session
        self._reranker = reranker
        self._repo = RetrievalResultRepository(session)

    async def run(self, ctx: QueryContext) -> None:
        if ctx.hybrid_result is None:
            msg = "RerankStage requires RetrievalStage.run to have populated hybrid_result."
            raise RuntimeError(msg)
        ctx.reranked = self._rerank(
            query=ctx.query,
            merged=ctx.hybrid_result.merged_candidates,
            top_k=ctx.retrieval_cfg.top_k_rerank,
        )
        if ctx.query_session_id is None:
            msg = "RerankStage requires SessionStage.open to have run first."
            raise RuntimeError(msg)
        await self._repo.add_many(
            tenant_id=ctx.auth.tenant_id,
            query_session_id=ctx.query_session_id,
            candidates=ctx.reranked,
        )

    def _rerank(
        self, *, query: str, merged: list[Candidate], top_k: int
    ) -> list[Candidate]:
        if not merged:
            return []
        if top_k <= 0:
            return [
                Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    content=c.content,
                    score=c.score,
                    rank=rank,
                    stage=RetrievalStageEnum.RERANK,
                    page_number=c.page_number,
                    section_title=c.section_title,
                    metadata={**c.metadata, "rerank_disabled": True},
                )
                for rank, c in enumerate(merged, start=1)
            ]
        rerank_inputs = [
            RerankCandidate(chunk_id=str(c.chunk_id), text=c.content) for c in merged
        ]
        try:
            result = self._reranker.rerank(
                query=query, candidates=rerank_inputs, top_k=top_k
            )
        except RerankerError:
            return [
                Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    content=c.content,
                    score=c.score,
                    rank=rank,
                    stage=RetrievalStageEnum.RERANK,
                    page_number=c.page_number,
                    section_title=c.section_title,
                    metadata={**c.metadata, "rerank_degraded": True},
                )
                for rank, c in enumerate(merged[:top_k], start=1)
            ]

        out: list[Candidate] = []
        for rank, (idx, score) in enumerate(
            zip(result.indices, result.scores, strict=True), start=1
        ):
            src = merged[idx]
            out.append(
                Candidate(
                    chunk_id=src.chunk_id,
                    document_id=src.document_id,
                    content=src.content,
                    score=score,
                    rank=rank,
                    stage=RetrievalStageEnum.RERANK,
                    page_number=src.page_number,
                    section_title=src.section_title,
                    metadata={**src.metadata, "reranker_model": result.model_name},
                )
            )
        return out
