"""RetrievalStage — invoke the RetrievalClient and persist per-stage rows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import RetrievalResultRepository
from app.services.rag.client import RetrievalClient
from app.services.rag.types import QueryContext


class RetrievalStage:
    def __init__(
        self,
        session: AsyncSession,
        retrieval_client: RetrievalClient,
    ) -> None:
        self._repo = RetrievalResultRepository(session)
        self._client = retrieval_client

    async def run(self, ctx: QueryContext) -> None:
        result = await self._client.retrieve(
            query=ctx.query,
            auth=ctx.auth,
            collection_ids=ctx.collection_ids,
            mode=ctx.retrieval_cfg.mode,
            top_k_bm25=ctx.retrieval_cfg.top_k_bm25,
            top_k_vector=ctx.retrieval_cfg.top_k_vector,
            top_k_hybrid=ctx.retrieval_cfg.top_k_hybrid,
            ef_search=ctx.retrieval_cfg.ef_search,
        )
        ctx.hybrid_result = result

        if ctx.query_session_id is None:
            msg = "RetrievalStage requires SessionStage.open to have run first."
            raise RuntimeError(msg)

        for stage_candidates in (
            result.bm25_candidates,
            result.vector_candidates,
            result.merged_candidates,
        ):
            await self._repo.add_many(
                tenant_id=ctx.auth.tenant_id,
                query_session_id=ctx.query_session_id,
                candidates=stage_candidates,
            )
