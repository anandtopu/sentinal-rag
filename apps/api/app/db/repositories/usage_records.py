"""Repository for ``usage_records`` rows.

``usage_records`` is partitioned; the existing
``TenantBudgetRepository.period_spend`` reads via raw SQL for the same
reason. Writes use the same approach so the partition-elimination plan is
preserved when we lean on the daily / monthly partitions in Phase 7.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The session is RLS-bound (app.current_tenant_id), so these aggregates are
# implicitly scoped to the caller's tenant. ``created_at`` is the partition key
# (indexed (tenant_id, created_at)), so the window predicate prunes partitions.
_SUMMARIZE_SQL = text(
    """
    SELECT
        COALESCE(SUM(total_cost_usd), 0) AS total_cost,
        COALESCE(SUM(input_tokens), 0)  AS input_tokens,
        COALESCE(SUM(output_tokens), 0) AS output_tokens,
        count(*)                        AS records
    FROM usage_records
    WHERE created_at >= :since AND created_at < :until
    """
)

_DAILY_SERIES_SQL = text(
    """
    SELECT
        (date_trunc('day', created_at AT TIME ZONE 'UTC'))::date AS day,
        COALESCE(SUM(total_cost_usd), 0) AS cost
    FROM usage_records
    WHERE created_at >= :since AND created_at < :until
    GROUP BY day
    ORDER BY day
    """
)


class UsageRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summarize(self, *, since: datetime, until: datetime) -> dict[str, Any]:
        """Total cost + token counts + record count over a window."""
        row = (
            await self._session.execute(_SUMMARIZE_SQL, {"since": since, "until": until})
        ).mappings().one()
        return dict(row)

    async def daily_series(self, *, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """Per-UTC-day total cost. Only non-empty days are returned; the service
        gap-fills the rest."""
        rows = (
            await self._session.execute(_DAILY_SERIES_SQL, {"since": since, "until": until})
        ).mappings().all()
        return [dict(r) for r in rows]

    async def create(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        query_session_id: UUID,
        usage_type: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        total_cost_usd: Decimal,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO usage_records "
                "(tenant_id, user_id, query_session_id, usage_type, provider, "
                " model_name, input_tokens, output_tokens, total_cost_usd) "
                "VALUES (:tid, :uid, :qs, :ut, :prov, :model, "
                "        :it, :ot, :cost)"
            ),
            {
                "tid": str(tenant_id),
                "uid": str(user_id),
                "qs": str(query_session_id),
                "ut": usage_type,
                "prov": provider,
                "model": model_name,
                "it": input_tokens,
                "ot": output_tokens,
                "cost": total_cost_usd,
            },
        )
