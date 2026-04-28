"""Role service."""

from __future__ import annotations

from uuid import UUID

from sentinelrag_shared.errors.exceptions import (
    ConflictError,
    RoleNotFoundError,
    ValidationFailedError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Role
from app.db.repositories import PermissionRepository, RoleRepository
from app.schemas.roles import RoleCreate, RoleUpdate


class RoleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = RoleRepository(db)
        self.permissions = PermissionRepository(db)

    async def create(self, *, tenant_id: UUID, payload: RoleCreate) -> Role:
        # Validate all permission codes exist before any writes.
        await self._validate_permission_codes(payload.permission_codes)

        existing = await self.repo.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError(f"Role '{payload.name}' already exists.")

        role = Role(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
        )
        self.db.add(role)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise ConflictError("Role could not be created.") from exc

        if payload.permission_codes:
            await self.repo.set_permissions(
                role_id=role.id, permission_codes=payload.permission_codes
            )
        return role

    async def get(self, role_id: UUID) -> Role:
        role = await self.repo.get(role_id)
        if role is None:
            raise RoleNotFoundError()
        return role

    async def list(self) -> list[Role]:
        return await self.repo.list(limit=200)

    async def update(self, role_id: UUID, payload: RoleUpdate) -> Role:
        role = await self.get(role_id)
        if payload.description is not None:
            role.description = payload.description
        if payload.permission_codes is not None:
            await self._validate_permission_codes(payload.permission_codes)
            await self.repo.set_permissions(
                role_id=role.id, permission_codes=payload.permission_codes
            )
        await self.db.flush()
        return role

    async def list_permission_codes(self, role_id: UUID) -> list[str]:
        # Make sure the role exists in the current tenant context (RLS) first.
        await self.get(role_id)
        return await self.repo.list_permission_codes(role_id)

    async def _validate_permission_codes(self, codes: list[str]) -> None:
        if not codes:
            return
        unique = set(codes)
        for code in unique:
            if (await self.permissions.get_by_code(code)) is None:
                raise ValidationFailedError(
                    f"Unknown permission code: {code}",
                    details={"code": code},
                )
