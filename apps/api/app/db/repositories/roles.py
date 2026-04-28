"""Role repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models import Permission, Role, RolePermission
from app.db.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_permissions(
        self,
        *,
        role_id: UUID,
        permission_codes: list[str],
    ) -> None:
        # Look up the permission IDs by code.
        if not permission_codes:
            permission_ids: list[UUID] = []
        else:
            stmt = select(Permission.id).where(Permission.code.in_(permission_codes))
            result = await self.session.execute(stmt)
            permission_ids = list(result.scalars().all())

        # Remove existing links, then add the new set. Done in two steps so
        # the operation is idempotent regardless of starting state.
        stmt_existing = select(RolePermission).where(RolePermission.role_id == role_id)
        existing = (await self.session.execute(stmt_existing)).scalars().all()
        for link in existing:
            await self.session.delete(link)
        for perm_id in permission_ids:
            self.session.add(RolePermission(role_id=role_id, permission_id=perm_id))
        await self.session.flush()

    async def list_permission_codes(self, role_id: UUID) -> list[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_user_permission_codes(self, user_id: UUID) -> set[str]:
        from app.db.models import UserRole  # noqa: PLC0415 — break import cycle

        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())
