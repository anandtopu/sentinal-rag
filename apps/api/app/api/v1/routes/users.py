"""User API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth, require_permission
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.users import UserCreate, UserRead, UserRoleAssign, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    payload: UserCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("users:write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    service = UserService(db)
    user = await service.create(tenant_id=ctx.tenant_id, payload=payload)
    return UserRead.model_validate(user)


@router.get(
    "",
    response_model=Page[UserRead],
)
async def list_users(
    _ctx: Annotated[AuthContext, Depends(require_permission("users:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserRead]:
    service = UserService(db)
    items = await service.list(limit=limit, offset=offset)
    return Page[UserRead](
        items=[UserRead.model_validate(u) for u in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/me",
    response_model=UserRead,
)
async def read_me(
    ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    service = UserService(db)
    user = await service.get(ctx.user_id)
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
)
async def read_user(
    user_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("users:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    service = UserService(db)
    user = await service.get(user_id)
    return UserRead.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    _ctx: Annotated[AuthContext, Depends(require_permission("users:write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    service = UserService(db)
    user = await service.update(user_id, payload)
    return UserRead.model_validate(user)


@router.post(
    "/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def assign_role(
    user_id: UUID,
    payload: UserRoleAssign,
    ctx: Annotated[AuthContext, Depends(require_permission("roles:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    service = UserService(db)
    await service.assign_role(
        user_id=user_id, role_id=payload.role_id, granted_by=ctx.user_id
    )
