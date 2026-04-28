"""Seed the demo tenant + admin user used by the dev-token auth bypass.

Idempotent: safe to re-run. Uses the admin (RLS-bypass) DB session because
the tenant doesn't exist yet on first run.

Usage:
    make seed
    # or
    uv run python scripts/seed/seed_demo.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Defaults match apps/api/app/core/config.py.
DEMO_TENANT_ID = UUID(os.environ.get("DEV_TENANT_ID", "00000000-0000-0000-0000-000000000001"))
DEMO_TENANT_SLUG = "demo"
DEMO_TENANT_NAME = "Demo Tenant"

DEMO_USER_ID = UUID(os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000010"))
DEMO_USER_EMAIL = os.environ.get("DEV_USER_EMAIL", "demo-admin@sentinelrag.example.com")

DEMO_ROLE_ID = UUID("00000000-0000-0000-0000-000000000020")
DEMO_ROLE_NAME = "demo-admin"


async def seed() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag",
    )
    engine = create_async_engine(dsn)

    async with engine.begin() as conn:
        # 1. Tenant.
        await conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, plan) "
                "VALUES (:id, :name, :slug, 'enterprise') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(DEMO_TENANT_ID), "name": DEMO_TENANT_NAME, "slug": DEMO_TENANT_SLUG},
        )

        # 2. User.
        await conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, full_name) "
                "VALUES (:id, :tid, :email, 'Demo Admin') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(DEMO_USER_ID), "tid": str(DEMO_TENANT_ID), "email": DEMO_USER_EMAIL},
        )

        # 3. Role.
        await conn.execute(
            text(
                "INSERT INTO roles (id, tenant_id, name, description) "
                "VALUES (:id, :tid, :name, 'Demo admin role with all permissions') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(DEMO_ROLE_ID), "tid": str(DEMO_TENANT_ID), "name": DEMO_ROLE_NAME},
        )

        # 4. Grant ALL permissions to the demo role.
        await conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT :rid, p.id FROM permissions p "
                "ON CONFLICT (role_id, permission_id) DO NOTHING"
            ),
            {"rid": str(DEMO_ROLE_ID)},
        )

        # 5. Assign role to user.
        await conn.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "VALUES (:uid, :rid) "
                "ON CONFLICT (user_id, role_id) DO NOTHING"
            ),
            {"uid": str(DEMO_USER_ID), "rid": str(DEMO_ROLE_ID)},
        )

        # 6. Pre-seed a demo collection so /documents has somewhere to land.
        await conn.execute(
            text(
                "INSERT INTO collections (id, tenant_id, name, description, "
                "                          visibility, created_by) "
                "VALUES ('00000000-0000-0000-0000-000000000030', "
                "        :tid, 'demo-collection', "
                "        'Pre-seeded for local smoke tests', 'tenant', :uid) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"tid": str(DEMO_TENANT_ID), "uid": str(DEMO_USER_ID)},
        )

    await engine.dispose()
    print(  # noqa: T201
        f"Seeded:\n"
        f"  tenant_id     = {DEMO_TENANT_ID}\n"
        f"  user_id       = {DEMO_USER_ID}\n"
        f"  user_email    = {DEMO_USER_EMAIL}\n"
        f"  role          = {DEMO_ROLE_NAME} (all permissions)\n"
        f"  collection_id = 00000000-0000-0000-0000-000000000030\n"
        f"\nTry it:\n"
        f"  curl -H 'Authorization: Bearer dev' http://localhost:8000/api/v1/users/me"
    )


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except Exception as exc:  # noqa: BLE001
        print(f"Seed failed: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
