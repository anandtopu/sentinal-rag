"""Async DB session factory for the retrieval-service.

Mirrors ``apps/api/app/db/session.py`` (RLS bound via
``app.current_tenant_id``), but stripped down — the retrieval-service
doesn't need admin sessions or repository wiring; it only opens a single
read transaction per request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinelrag_retrieval_service.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_SET_TENANT_SQL: Final = text("SELECT set_config('app.current_tenant_id', :tid, true)")


def get_engine() -> AsyncEngine:
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            future=True,
        )
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


async def open_tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Yield an RLS-bound session for a single retrieve() call.

    The retrieval-service handles many tenants per process; we set the
    tenant context from the request body's AuthContext rather than from
    a contextvar (no FastAPI middleware involved).
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})
        yield session


async def dispose_engine() -> None:
    global _engine  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
