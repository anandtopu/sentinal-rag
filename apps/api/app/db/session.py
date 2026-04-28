"""Async DB session factory + tenant-context-aware session checkout.

Two contextvars drive RLS enforcement:
    - ``current_tenant_id`` — UUID of the tenant for the current request.
      Set by the auth middleware on every authenticated request.
    - ``current_user_id`` — UUID of the actor for audit purposes.

Each new SQLAlchemy session runs ``SET LOCAL app.current_tenant_id = '<uuid>'``
before any application query so the RLS policies on every tenant-owned table
filter correctly.

There is also a privileged session factory (``get_admin_session``) for the few
operations that legitimately need to skip RLS — exclusively tenant-creation
flows and migration smoke tests. Service code MUST NOT use it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

# --- Context variables (per-request) ---
current_tenant_id: ContextVar[UUID | None] = ContextVar("current_tenant_id", default=None)
current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


# --- Engine + session factories ---
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_admin_engine: AsyncEngine | None = None
_admin_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(*, admin: bool = False) -> AsyncEngine:
    settings = get_settings()
    # The admin engine connects without setting RLS context; intended for tenant
    # provisioning + tests. In production this engine uses a separate role
    # (e.g. ``sentinelrag_admin``) — for v1 the same DSN is used in dev.
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10 if not admin else 2,
        max_overflow=20 if not admin else 5,
        future=True,
    )


def get_engine() -> AsyncEngine:
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def _get_admin_session_factory() -> async_sessionmaker[AsyncSession]:
    global _admin_engine, _admin_session_factory  # noqa: PLW0603
    if _admin_session_factory is None:
        _admin_engine = _build_engine(admin=True)
        _admin_session_factory = async_sessionmaker(
            bind=_admin_engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return _admin_session_factory


# --- Session lifecycle ---
_SET_TENANT_SQL: Final = text("SELECT set_config('app.current_tenant_id', :tid, true)")


async def _bind_tenant_context(session: AsyncSession) -> None:
    """Issue ``SET LOCAL app.current_tenant_id`` for the active tenant.

    ``set_config(..., true)`` is the function-call form of ``SET LOCAL``; it
    only persists for the duration of the current transaction, which is the
    behavior we want.
    """
    tid = current_tenant_id.get()
    if tid is None:
        # No tenant in context → set to NULL marker so RLS denies everything
        # rather than fall back to the previous transaction's setting.
        await session.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
        return
    await session.execute(_SET_TENANT_SQL, {"tid": str(tid)})


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an RLS-bound async session.

    Usage::

        @router.get("/users")
        async def list_users(db: Annotated[AsyncSession, Depends(get_db)]) -> ...:
            ...
    """
    factory = get_session_factory()
    # Open a transaction so SET LOCAL persists across queries within the
    # request. Commit on success, rollback on exception.
    async with factory() as session, session.begin():
        await _bind_tenant_context(session)
        yield session


async def get_admin_db() -> AsyncIterator[AsyncSession]:
    """Privileged session that bypasses tenant context.

    USE ONLY FOR:
        - Tenant CREATE (no tenant exists yet to scope to).
        - Platform-wide reads of ``permissions`` (which is intentionally
          unscoped).

    Service code that uses this dependency requires explicit RBAC checks for
    the actor's ``platform-admin`` role.
    """
    factory = _get_admin_session_factory()
    async with factory() as session, session.begin():
        yield session


async def dispose_engines() -> None:
    """Tear down engines on shutdown (called from lifespan)."""
    global _engine, _admin_engine  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _admin_engine is not None:
        await _admin_engine.dispose()
        _admin_engine = None
