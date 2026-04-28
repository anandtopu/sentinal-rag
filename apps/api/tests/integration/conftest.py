"""Shared fixtures for integration tests.

Uses testcontainers to spin up a real ``pgvector/pgvector:pg16`` Postgres,
runs all Alembic migrations end-to-end, and yields an async session bound to
the real DB. Each test gets a clean schema via a per-test transactional roll-
back wouldn't work here (RLS sets are per-transaction); we instead truncate
seeded rows in the function-scope teardown.

NB: requires Docker available on the test runner.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import alembic.config
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """Spin up a single Postgres for the whole test session."""
    with PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="sentinel",
        password="sentinel",
        dbname="sentinelrag",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def database_urls(postgres_container: PostgresContainer) -> dict[str, str]:
    """Async + sync DSNs for the running container."""
    sync_url = postgres_container.get_connection_url()  # postgresql+psycopg2://...
    # Normalize to plain postgresql:// for psycopg3 (Alembic env.py),
    # and asyncpg variant for the application.
    sync_url = sync_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    async_url = sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return {"sync": sync_url, "async": async_url}


@pytest.fixture(scope="session")
def applied_migrations(database_urls: dict[str, str]) -> dict[str, str]:
    """Apply all Alembic migrations against the test container once per session."""
    os.environ["DATABASE_URL_SYNC"] = database_urls["sync"]
    os.environ["DATABASE_URL"] = database_urls["async"]

    cfg = alembic.config.Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic.config.command.upgrade(cfg, "head")
    return database_urls


@pytest_asyncio.fixture
async def engine(applied_migrations: dict[str, str]):
    """Async engine for tests; one per test for isolation of pool state."""
    eng = create_async_engine(applied_migrations["async"], pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def admin_session(
    cleanup_db, session_factory
) -> AsyncIterator[AsyncSession]:
    """Session that does NOT bind tenant context. Bypasses RLS as table owner.

    Tests must ``await admin_session.commit()`` after seeding so concurrent
    sessions opened through ``tenant_session_factory`` (separate connections,
    READ COMMITTED isolation) can observe the rows. The fixture depends on
    ``cleanup_db`` so cleanup_db's TRUNCATE teardown runs *after* this fixture
    rolls back any leftover transaction — otherwise the TRUNCATE deadlocks on
    locks held by the admin transaction.
    """
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def _bind_tenant_role(
    session: AsyncSession, tenant_id: UUID | None
) -> None:
    """Bind a transaction to the runtime role + tenant context.

    Tests connect as the testcontainer's ``sentinel`` superuser, which bypasses
    RLS. To exercise RLS we ``SET LOCAL ROLE sentinelrag_app`` (the runtime
    role created by migration 0010, with no BYPASSRLS attribute) — that's the
    role the application uses in production.

    For ``tenant_id=None`` (the unbound-session test) we deliberately skip the
    ``set_config`` call so ``current_setting('app.current_tenant_id', true)``
    returns NULL → ``NULL::uuid`` → policies match no rows. Setting the GUC
    to ``''`` would fail with ``invalid_text_representation`` when the policy
    casts to uuid.
    """
    await session.execute(text("SET LOCAL ROLE sentinelrag_app"))
    if tenant_id is not None:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :v, true)"),
            {"v": str(tenant_id)},
        )


@pytest_asyncio.fixture
async def tenant_session_factory(session_factory):
    """Returns a callable that yields an RLS-bound session for a given tenant."""

    def _factory(tenant_id: UUID | None):
        async def _ctx() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session, session.begin():
                await _bind_tenant_role(session, tenant_id)
                yield session

        return _ctx

    return _factory


@pytest_asyncio.fixture
async def cleanup_db(session_factory) -> AsyncIterator[None]:
    """After each test, truncate all tenant-owned tables (preserves migrations + permissions)."""
    yield
    async with session_factory() as session, session.begin():
        # Order matters — truncate-with-cascade handles FKs.
        await session.execute(
            text(
                "TRUNCATE TABLE "
                "chunk_embeddings, document_chunks, document_versions, documents, "
                "ingestion_jobs, collection_access_policies, collections, "
                "user_roles, role_permissions, users, roles, tenants "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def tenant_factory():
    """Helper to mint tenant UUIDs in tests."""

    def _make() -> UUID:
        return uuid4()

    return _make


# ---- MinIO container (for ingestion tests) ----
@pytest.fixture(scope="session")
def minio_container() -> Iterator[MinioContainer]:
    """Single MinIO container shared across the test session."""
    with MinioContainer(
        image="minio/minio:latest",
        access_key="minioadmin",
        secret_key="minioadmin",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def minio_endpoint(minio_container: MinioContainer) -> str:
    cfg = minio_container.get_config()
    # cfg["endpoint"] is host:port, no scheme.
    return f"http://{cfg['endpoint']}"


@pytest_asyncio.fixture
async def minio_with_bucket(minio_endpoint: str) -> str:
    """Ensure the documents bucket exists. Returns the endpoint URL."""
    from sentinelrag_shared.object_storage import build_object_storage  # noqa: PLC0415
    from sentinelrag_shared.object_storage.s3 import S3Storage  # noqa: PLC0415

    # MinIO container creates a default bucket only if MINIO_DEFAULT_BUCKETS is
    # set; the testcontainers helper doesn't set it, so we create explicitly.
    storage: S3Storage = build_object_storage(  # type: ignore[assignment]
        provider="minio",
        bucket="sentinelrag-documents",
        region="us-east-1",
        endpoint=minio_endpoint,
        access_key="minioadmin",
        secret_key="minioadmin",
        verify_ssl=False,
    )
    # Create bucket if it doesn't exist (S3 ``CreateBucket`` is idempotent
    # with the right error handling, but we just call it best-effort).
    try:
        async with storage._session.client(
            "s3", **storage._client_kwargs()
        ) as s3:
            with contextlib.suppress(Exception):  # already exists is fine
                await s3.create_bucket(Bucket="sentinelrag-documents")
    finally:
        await storage.close()
    return minio_endpoint


# ---- Mocked Temporal client (for route-level ingestion tests) ----
@pytest.fixture
def mock_temporal_client():
    """A Temporal client mock that records start_workflow calls."""
    client = MagicMock()
    client.start_workflow = AsyncMock(return_value=MagicMock())
    return client
