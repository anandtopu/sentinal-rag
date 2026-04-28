"""Collection repository."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import Collection
from app.db.repositories.base import BaseRepository


class CollectionRepository(BaseRepository[Collection]):
    model = Collection

    async def get_by_name(self, name: str) -> Collection | None:
        stmt = select(Collection).where(Collection.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
