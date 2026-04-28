"""Integration tests for the repository + service layer with RLS in place."""

from __future__ import annotations

import pytest
from app.db.models import Tenant
from app.db.repositories import RoleRepository, UserRepository
from app.schemas.roles import RoleCreate
from app.schemas.users import UserCreate
from app.services.role_service import RoleService
from app.services.user_service import UserService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
class TestPhase1Services:
    async def _seed_tenant(self, admin_session: AsyncSession) -> Tenant:
        tenant = Tenant(name="Cybertron", slug="cybertron", plan="enterprise")
        admin_session.add(tenant)
        await admin_session.commit()
        await admin_session.refresh(tenant)
        return tenant

    async def test_create_user_then_assign_role_then_resolve_permissions(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        tenant = await self._seed_tenant(admin_session)

        get_tenant_session = tenant_session_factory(tenant.id)

        # 1. Create a role with a permission.
        async for sess in get_tenant_session():
            role_svc = RoleService(sess)
            role = await role_svc.create(
                tenant_id=tenant.id,
                payload=RoleCreate(
                    name="editor",
                    description="Can write users",
                    permission_codes=["users:write", "users:read"],
                ),
            )
            role_id = role.id

        # 2. Create a user.
        async for sess in get_tenant_session():
            user_svc = UserService(sess)
            user = await user_svc.create(
                tenant_id=tenant.id,
                payload=UserCreate(email="alice@cybertron.example.com", full_name="Alice"),
            )
            user_id = user.id

        # 3. Assign role.
        async for sess in get_tenant_session():
            user_svc = UserService(sess)
            await user_svc.assign_role(
                user_id=user_id, role_id=role_id, granted_by=user_id
            )

        # 4. Resolve permissions for the user.
        async for sess in get_tenant_session():
            role_repo = RoleRepository(sess)
            perms = await role_repo.list_user_permission_codes(user_id)
            assert perms == {"users:write", "users:read"}

    async def test_user_email_uniqueness_within_tenant(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        tenant = await self._seed_tenant(admin_session)

        get_session = tenant_session_factory(tenant.id)

        async for sess in get_session():
            svc = UserService(sess)
            await svc.create(
                tenant_id=tenant.id,
                payload=UserCreate(email="dup@cybertron.example.com"),
            )

        async for sess in get_session():
            svc = UserService(sess)
            with pytest.raises(Exception):  # noqa: B017,PT011
                await svc.create(
                    tenant_id=tenant.id,
                    payload=UserCreate(email="DUP@cybertron.example.com"),
                )

    async def test_user_repo_lookup_by_email_is_case_insensitive_via_service(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        tenant = await self._seed_tenant(admin_session)
        get_session = tenant_session_factory(tenant.id)

        async for sess in get_session():
            svc = UserService(sess)
            await svc.create(
                tenant_id=tenant.id,
                payload=UserCreate(email="MixedCase@cybertron.example.com"),
            )

        async for sess in get_session():
            user_repo = UserRepository(sess)
            user = await user_repo.get_by_email("mixedcase@cybertron.example.com")
            assert user is not None
            assert user.email == "mixedcase@cybertron.example.com"
