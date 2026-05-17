"""Repository for ``generated_answers`` rows."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class GeneratedAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        query_session_id: UUID,
        answer_text: str,
        model_provider: str,
        model_name: str,
        prompt_version_id: UUID | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        grounding_score: float | None,
    ) -> UUID:
        new_id = uuid4()
        await self._session.execute(
            text(
                "INSERT INTO generated_answers "
                "(id, tenant_id, query_session_id, answer_text, model_provider, "
                " model_name, prompt_version_id, input_tokens, output_tokens, "
                " cost_usd, grounding_score) "
                "VALUES (:id, :tid, :qs, :ans, :prov, :model, :pv, "
                "        :it, :ot, :cost, :ground)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "qs": str(query_session_id),
                "ans": answer_text,
                "prov": model_provider,
                "model": model_name,
                "pv": str(prompt_version_id) if prompt_version_id else None,
                "it": input_tokens,
                "ot": output_tokens,
                "cost": cost_usd,
                "ground": grounding_score,
            },
        )
        return new_id
