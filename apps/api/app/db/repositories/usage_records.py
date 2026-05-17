"""Repository for ``usage_records`` rows.

``usage_records`` is partitioned; the existing
``TenantBudgetRepository.period_spend`` reads via raw SQL for the same
reason. Writes use the same approach so the partition-elimination plan is
preserved when we lean on the daily / monthly partitions in Phase 7.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UsageRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
