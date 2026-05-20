"""Query-history feed service (BACKLOG B10 #3).

Thin read-model over ``query_sessions`` (joined to ``generated_answers``)
following the pattern established in ADR-0038. Maps raw repository rows to the
``QuerySessionListItem`` API shape; the mapping lives here so it's unit-testable
with a fake repository, while the raw SQL stays in ``QuerySessionRepository``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.query_sessions import QuerySessionRepository
from app.schemas.query import QuerySessionListItem


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


class QueryHistoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.queries = QuerySessionRepository(db)

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[QuerySessionListItem]:
        rows = await self.queries.list_recent(limit=limit, offset=offset)
        return [self._to_item(r) for r in rows]

    @staticmethod
    def _to_item(row: dict[str, Any]) -> QuerySessionListItem:
        return QuerySessionListItem(
            id=row["id"],
            query=row["query_text"],
            status=row["status"],
            latency_ms=row.get("latency_ms"),
            grounding_score=_as_float(row.get("grounding_score")),
            model=row.get("model_name"),
            created_at=row["created_at"],
        )
