"""Role + permission API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth, require_permission
from app.db.repositories import PermissionRepository
from app.db.session import get_db
from app.schemas.roles import PermissionRead, RoleCreate, RoleRead, RoleUpdate
from app.services.role_service import RoleService

router = APIRouter(tags=["roles"])


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    _ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PermissionRead]:
    repo = PermissionRepository(db)
    perms = await repo.list_all()
    return [PermissionRead.model_validate(p) for p in perms]


@router.post(
    "/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    payload: RoleCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("roles:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleRead:
    service = RoleService(db)
    role = await service.create(tenant_id=ctx.tenant_id, payload=payload)
    codes = await service.list_permission_codes(role.id)
    return RoleRead.model_validate({**role.__dict__, "permission_codes": codes})


@router.get(
    "/roles",
    response_model=list[RoleRead],
)
async def list_roles(
    _ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoleRead]:
    service = RoleService(db)
    roles = await service.list()
    out: list[RoleRead] = []
    for role in roles:
        codes = await service.list_permission_codes(role.id)
        out.append(RoleRead.model_validate({**role.__dict__, "permission_codes": codes}))
    return out


@router.get(
    "/roles/{role_id}",
    response_model=RoleRead,
)
async def read_role(
    role_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleRead:
    service = RoleService(db)
    role = await service.get(role_id)
    codes = await service.list_permission_codes(role.id)
    return RoleRead.model_validate({**role.__dict__, "permission_codes": codes})


@router.patch(
    "/roles/{role_id}",
    response_model=RoleRead,
)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    _ctx: Annotated[AuthContext, Depends(require_permission("roles:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleRead:
    service = RoleService(db)
    role = await service.update(role_id, payload)
    codes = await service.list_permission_codes(role.id)
    return RoleRead.model_validate({**role.__dict__, "permission_codes": codes})
