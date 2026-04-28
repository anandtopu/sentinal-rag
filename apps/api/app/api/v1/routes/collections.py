"""Collection routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.session import get_db
from app.schemas.collections import CollectionCreate, CollectionRead, CollectionUpdate
from app.schemas.common import Page
from app.services.collection_service import CollectionService

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post(
    "",
    response_model=CollectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    payload: CollectionCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("collections:write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CollectionRead:
    service = CollectionService(db)
    coll = await service.create(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payload=payload
    )
    return CollectionRead.model_validate(coll)


@router.get("", response_model=Page[CollectionRead])
async def list_collections(
    _ctx: Annotated[AuthContext, Depends(require_permission("collections:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CollectionRead]:
    service = CollectionService(db)
    items = await service.list(limit=limit, offset=offset)
    return Page[CollectionRead](
        items=[CollectionRead.model_validate(c) for c in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/{collection_id}", response_model=CollectionRead)
async def read_collection(
    collection_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("collections:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CollectionRead:
    service = CollectionService(db)
    coll = await service.get(collection_id)
    return CollectionRead.model_validate(coll)


@router.patch("/{collection_id}", response_model=CollectionRead)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    _ctx: Annotated[AuthContext, Depends(require_permission("collections:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CollectionRead:
    service = CollectionService(db)
    coll = await service.update(collection_id, payload)
    return CollectionRead.model_validate(coll)
