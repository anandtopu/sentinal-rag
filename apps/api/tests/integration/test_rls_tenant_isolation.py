"""RLS proof: a session bound to tenant A cannot read or write tenant B's rows.

These tests are the headline of Phase 1. If they pass against a real Postgres
with the migrations applied, our tenant-isolation guarantee is real.
"""

from __future__ import annotations

import pytest
from app.db.models import Tenant, User
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
class TestRowLevelSecurity:
    async def _seed_two_tenants_with_users(
        self, admin_session: AsyncSession
    ) -> tuple[Tenant, Tenant, User, User]:
        """Use the admin (RLS-bypass) session to seed two tenants + one user each."""
        tenant_a = Tenant(name="Acme", slug="acme", plan="enterprise")
        tenant_b = Tenant(name="Beacon", slug="beacon", plan="enterprise")
        admin_session.add_all([tenant_a, tenant_b])
        await admin_session.flush()

        user_a = User(tenant_id=tenant_a.id, email="alice@acme.test", full_name="Alice")
        user_b = User(tenant_id=tenant_b.id, email="bob@beacon.test", full_name="Bob")
        admin_session.add_all([user_a, user_b])
        await admin_session.commit()
        for obj in (tenant_a, tenant_b, user_a, user_b):
            await admin_session.refresh(obj)
        return tenant_a, tenant_b, user_a, user_b

    async def test_tenant_a_session_only_sees_tenant_a_users(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        tenant_a, tenant_b, user_a, _user_b = await self._seed_two_tenants_with_users(
            admin_session
        )

        # Session bound to tenant_a sees user_a only.
        get_a = tenant_session_factory(tenant_a.id)
        async for sess in get_a():
            result = await sess.execute(text("SELECT id FROM users"))
            visible = {row[0] for row in result.fetchall()}
            assert visible == {user_a.id}

        # Session bound to tenant_b cannot see user_a.
        get_b = tenant_session_factory(tenant_b.id)
        async for sess in get_b():
            result = await sess.execute(
                text("SELECT id FROM users WHERE id = :uid"), {"uid": user_a.id}
            )
            assert result.fetchone() is None

    async def test_tenant_a_session_cannot_insert_into_tenant_b(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        tenant_a, tenant_b, _user_a, _user_b = await self._seed_two_tenants_with_users(
            admin_session
        )

        get_a = tenant_session_factory(tenant_a.id)
        async for sess in get_a():
            with pytest.raises(DBAPIError):
                await sess.execute(
                    text(
                        "INSERT INTO users (tenant_id, email) "
                        "VALUES (:tid, 'eve@acme.test')"
                    ),
                    {"tid": tenant_b.id},
                )

    async def test_unbound_session_sees_nothing(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        await self._seed_two_tenants_with_users(admin_session)

        # No tenant_id set → app.current_tenant_id is empty → policy denies all rows.
        get_none = tenant_session_factory(None)
        async for sess in get_none():
            result = await sess.execute(text("SELECT count(*) FROM users"))
            assert result.scalar_one() == 0

    async def test_admin_session_sees_all_tenants(
        self,
        admin_session: AsyncSession,
        cleanup_db,
    ) -> None:
        # Admin session is the table owner → RLS doesn't apply.
        await self._seed_two_tenants_with_users(admin_session)
        result = await admin_session.execute(text("SELECT count(*) FROM users"))
        assert result.scalar_one() == 2
