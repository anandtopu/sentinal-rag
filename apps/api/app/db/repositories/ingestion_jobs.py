"""IngestionJob repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models import IngestionJob
from app.db.repositories.base import BaseRepository


class IngestionJobRepository(BaseRepository[IngestionJob]):
    model = IngestionJob

    async def list_for_collection(
        self, collection_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[IngestionJob]:
        stmt = (
            select(IngestionJob)
            .where(IngestionJob.collection_id == collection_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_workflow_id(self, workflow_id: str) -> IngestionJob | None:
        stmt = select(IngestionJob).where(IngestionJob.workflow_id == workflow_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
