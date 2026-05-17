"""Repository for ``retrieval_results`` rows.

One row per (query_session, chunk, stage). The orchestrator persists each
stage's candidates (bm25, vector, hybrid_merge, rerank) so the trace UI can
show which path contributed.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sentinelrag_shared.retrieval import Candidate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _json_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)


class RetrievalResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(
        self,
        *,
        tenant_id: UUID,
        query_session_id: UUID,
        candidates: list[Candidate],
    ) -> None:
        if not candidates:
            return
        for cand in candidates:
            await self._session.execute(
                text(
                    "INSERT INTO retrieval_results "
                    "(tenant_id, query_session_id, chunk_id, retrieval_stage, "
                    " rank, score, metadata) "
                    "VALUES (:tid, :qs, :cid, :stage, :rank, :score, "
                    "        CAST(:meta AS jsonb))"
                ),
                {
                    "tid": str(tenant_id),
                    "qs": str(query_session_id),
                    "cid": str(cand.chunk_id),
                    "stage": cand.stage.value,
                    "rank": cand.rank,
                    "score": cand.score,
                    "meta": _json_dumps(cand.metadata),
                },
            )
