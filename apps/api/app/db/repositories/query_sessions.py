"""Repository for ``query_sessions`` rows.

No ORM model is defined for ``query_sessions`` — the orchestrator only ever
writes via the bounded operations exposed here and never needs a fully
hydrated row object. Raw SQL stays inside the repository so the partition
plan (the audit + usage tables it joins to are partitioned) is preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Ordered-set aggregates (percentile_cont) ignore NULL latency_ms, so the
# in-flight ('running') rows that have no latency yet don't skew percentiles.
# The session is RLS-bound (app.current_tenant_id), so every aggregate below
# is implicitly scoped to the caller's tenant (ADR-0038, pillar #2).
_WINDOW_AGGREGATE_SQL = text(
    """
    SELECT
        count(*) FILTER (WHERE status <> 'running')   AS total,
        count(*) FILTER (WHERE status = 'failed')     AS failed,
        count(*) FILTER (WHERE status = 'abstained')  AS abstained,
        count(latency_ms)                             AS latency_count,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS p50,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99
    FROM query_sessions
    WHERE created_at >= :since AND created_at < :until
    """
)

_BUCKET_AGGREGATE_SQL = text(
    """
    SELECT
        date_bin(CAST(:grain AS interval), created_at, :origin) AS bucket_start,
        count(*) FILTER (WHERE status <> 'running') AS queries,
        count(*) FILTER (WHERE status = 'failed')   AS errors,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
    FROM query_sessions
    WHERE created_at >= :since AND created_at < :until
    GROUP BY bucket_start
    ORDER BY bucket_start
    """
)

# One generated_answer per session (the orchestrator writes exactly one), so a
# plain LEFT JOIN doesn't fan out. RLS scopes both tables to the tenant.
_LIST_RECENT_SQL = text(
    """
    SELECT
        qs.id, qs.query_text, qs.status, qs.latency_ms, qs.created_at,
        ga.grounding_score, ga.model_name
    FROM query_sessions qs
    LEFT JOIN generated_answers ga ON ga.query_session_id = qs.id
    ORDER BY qs.created_at DESC
    LIMIT :limit OFFSET :offset
    """
)


class QuerySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def window_aggregate(self, *, since: datetime, until: datetime) -> dict[str, Any]:
        """Scalar aggregate (counts + latency percentiles) over a window.

        Returns a single row even when no sessions match — counts are 0 and
        percentiles are ``None``.
        """
        row = (
            await self._session.execute(
                _WINDOW_AGGREGATE_SQL, {"since": since, "until": until}
            )
        ).mappings().one()
        return dict(row)

    async def bucket_aggregate(
        self, *, since: datetime, until: datetime, grain: str, origin: datetime
    ) -> list[dict[str, Any]]:
        """Per-bucket aggregate via ``date_bin``. Only non-empty buckets are
        returned; the service gap-fills the rest so the sparkline is
        continuous."""
        rows = (
            await self._session.execute(
                _BUCKET_AGGREGATE_SQL,
                {"since": since, "until": until, "grain": grain, "origin": origin},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def list_recent(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        """Recent query sessions (newest first) with their grounding score +
        model, for the query-history feed (BACKLOG B10 #3)."""
        rows = (
            await self._session.execute(_LIST_RECENT_SQL, {"limit": limit, "offset": offset})
        ).mappings().all()
        return [dict(r) for r in rows]

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
