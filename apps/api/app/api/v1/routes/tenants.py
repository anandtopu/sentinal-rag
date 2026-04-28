"""Tenant API routes.

Tenant CREATE is a platform-admin operation (uses the admin DB session,
bypassing RLS). Tenant READ/UPDATE for the current tenant uses the standard
RLS-bound session: a user can only see their own tenant.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_auth, require_permission
from app.db.session import get_admin_db, get_db
from app.schemas.tenants import TenantCreate, TenantRead, TenantUpdate
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant (platform-admin)",
)
async def create_tenant(
    payload: TenantCreate,
    _ctx: Annotated[AuthContext, Depends(require_permission("tenants:admin"))],
    db: Annotated[AsyncSession, Depends(get_admin_db)],
) -> TenantRead:
    service = TenantService(db)
    tenant = await service.create(payload)
    return TenantRead.model_validate(tenant)


@router.get(
    "/me",
    response_model=TenantRead,
    summary="Read the current tenant",
)
async def read_my_tenant(
    ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantRead:
    service = TenantService(db)
    tenant = await service.get(ctx.tenant_id)
    return TenantRead.model_validate(tenant)


@router.get(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Read a tenant by id (RLS-scoped)",
)
async def read_tenant(
    tenant_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantRead:
    # RLS makes the cross-tenant case return None → 404.
    service = TenantService(db)
    tenant = await service.get(tenant_id)
    return TenantRead.model_validate(tenant)


@router.patch(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Update tenant settings",
)
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    _ctx: Annotated[AuthContext, Depends(require_permission("tenants:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantRead:
    service = TenantService(db)
    tenant = await service.update(tenant_id, payload)
    return TenantRead.model_validate(tenant)
