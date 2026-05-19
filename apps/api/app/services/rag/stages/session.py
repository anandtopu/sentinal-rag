"""SessionStage — open + close the ``query_sessions`` row via the repository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import QuerySessionRepository
from app.services.rag.types import QueryContext


class SessionStage:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = QuerySessionRepository(session)

    async def open(self, ctx: QueryContext) -> None:
        ctx.query_session_id = await self._repo.create(
            tenant_id=ctx.auth.tenant_id,
            user_id=ctx.auth.user_id,
            query_text=ctx.query,
            normalized_query=" ".join(ctx.query.lower().split()),
            collection_ids=ctx.collection_ids,
        )

    async def close(
        self,
        ctx: QueryContext,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Set terminal status, latency, accumulated cost, and optional error."""
        if ctx.query_session_id is None:
            msg = "SessionStage.close called before open."
            raise RuntimeError(msg)
        await self._repo.set_terminal(
            query_session_id=ctx.query_session_id,
            status=status,
            latency_ms=ctx.latency_ms,
            total_cost_usd=float(ctx.gen_cost),
            error_message=error_message,
        )
