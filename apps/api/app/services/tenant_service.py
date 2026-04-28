"""Tenant service.

Tenant CREATE is a privileged operation: the actor must hold ``tenants:admin``
permission on a "platform" scope, AND the database session used for creation
must be the admin (RLS-bypass) one — there's no tenant context yet for the
new tenant.

Tenant READ is RLS-scoped: a tenant can only read its own row.
"""

from __future__ import annotations

from uuid import UUID

from sentinelrag_shared.errors.exceptions import ConflictError, TenantNotFoundError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant
from app.db.repositories import TenantRepository
from app.schemas.tenants import TenantCreate, TenantUpdate


class TenantService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TenantRepository(db)

    async def create(self, payload: TenantCreate) -> Tenant:
        existing = await self.repo.get_by_slug(payload.slug)
        if existing is not None:
            raise ConflictError(f"Tenant slug '{payload.slug}' is already taken.")

        tenant = Tenant(
            name=payload.name,
            slug=payload.slug,
            plan=payload.plan,
            metadata_=payload.metadata,
        )
        self.db.add(tenant)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise ConflictError("Tenant could not be created (constraint violation).") from exc
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant:
        tenant = await self.repo.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError()
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        tenant = await self.repo.get_by_slug(slug)
        if tenant is None:
            raise TenantNotFoundError()
        return tenant

    async def update(self, tenant_id: UUID, payload: TenantUpdate) -> Tenant:
        tenant = await self.get(tenant_id)
        if payload.name is not None:
            tenant.name = payload.name
        if payload.plan is not None:
            tenant.plan = payload.plan
        if payload.status is not None:
            tenant.status = payload.status
        if payload.metadata is not None:
            tenant.metadata_ = payload.metadata
        await self.db.flush()
        return tenant
