"""Repository for ``answer_citations`` rows."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AnswerCitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        generated_answer_id: UUID,
        chunk_id: UUID,
        citation_index: int,
        quoted_text: str | None,
        relevance_score: float | None,
    ) -> UUID:
        new_id = uuid4()
        await self._session.execute(
            text(
                "INSERT INTO answer_citations "
                "(id, tenant_id, generated_answer_id, chunk_id, "
                " citation_index, quoted_text, relevance_score) "
                "VALUES (:id, :tid, :ga, :cid, :idx, :qt, :score)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "ga": str(generated_answer_id),
                "cid": str(chunk_id),
                "idx": citation_index,
                "qt": quoted_text,
                "score": relevance_score,
            },
        )
        return new_id
