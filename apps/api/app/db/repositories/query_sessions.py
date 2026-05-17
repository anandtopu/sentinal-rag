"""Repository for ``query_sessions`` rows.

No ORM model is defined for ``query_sessions`` — the orchestrator only ever
writes via the bounded operations exposed here and never needs a fully
hydrated row object. Raw SQL stays inside the repository so the partition
plan (the audit + usage tables it joins to are partitioned) is preserved.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class QuerySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_text: str,
        normalized_query: str,
        collection_ids: list[UUID],
    ) -> UUID:
        new_id = uuid4()
        await self._session.execute(
            text(
                "INSERT INTO query_sessions "
                "(id, tenant_id, user_id, query_text, normalized_query, "
                " collection_ids, status) "
                "VALUES (:id, :tid, :uid, :q, :nq, "
                "        CAST(:cids AS uuid[]), 'running')"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "uid": str(user_id),
                "q": query_text,
                "nq": normalized_query,
                "cids": [str(c) for c in collection_ids],
            },
        )
        return new_id

    async def set_terminal(
        self,
        *,
        query_session_id: UUID,
        status: str,
        latency_ms: int,
        total_cost_usd: float,
        error_message: str | None = None,
    ) -> None:
        """Mark a session terminal with optional structured error message.

        The dedicated ``error_message`` column was added in migration 0015
        (R1.S3), replacing the prior workaround of concatenating onto
        ``normalized_query``.
        """
        await self._session.execute(
            text(
                "UPDATE query_sessions "
                "SET status=:status, latency_ms=:lat, total_cost_usd=:cost, "
                "    error_message=:err "
                "WHERE id=:id"
            ),
            {
                "id": str(query_session_id),
                "status": status,
                "lat": latency_ms,
                "cost": total_cost_usd,
                "err": error_message[:500] if error_message else None,
            },
        )
