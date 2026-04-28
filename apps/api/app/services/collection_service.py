"""Collection service."""

from __future__ import annotations

from uuid import UUID

from sentinelrag_shared.errors.exceptions import (
    ConflictError,
    NotFoundError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Collection
from app.db.repositories import CollectionRepository
from app.schemas.collections import CollectionCreate, CollectionUpdate


class CollectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CollectionRepository(db)

    async def create(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID | None,
        payload: CollectionCreate,
    ) -> Collection:
        existing = await self.repo.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError(f"Collection '{payload.name}' already exists.")

        collection = Collection(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            visibility=payload.visibility,
            metadata_=payload.metadata,
            created_by=created_by,
        )
        self.db.add(collection)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise ConflictError("Collection could not be created.") from exc
        return collection

    async def get(self, collection_id: UUID) -> Collection:
        collection = await self.repo.get(collection_id)
        if collection is None:
            raise NotFoundError("Collection not found.")
        return collection

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Collection]:
        return await self.repo.list(limit=limit, offset=offset)

    async def update(
        self, collection_id: UUID, payload: CollectionUpdate
    ) -> Collection:
        collection = await self.get(collection_id)
        if payload.description is not None:
            collection.description = payload.description
        if payload.visibility is not None:
            collection.visibility = payload.visibility
        if payload.metadata is not None:
            collection.metadata_ = payload.metadata
        await self.db.flush()
        return collection
