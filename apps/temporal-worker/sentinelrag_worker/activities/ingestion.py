"""Ingestion activities.

All activities open a fresh DB session per call and bind the tenant context
explicitly — workers don't have the FastAPI request lifecycle so we can't
rely on contextvars set by middleware. The pattern is:

    async with _session_for_tenant(tenant_id) as session:
        ...

Activity functions are top-level (not methods) so Temporal can serialize
their references for replay.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pickle
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

# These imports come from sentinelrag-shared and from the API package which
# defines the ORM models. The Temporal worker container installs both.
from sentinelrag_shared.object_storage import ObjectStorage, build_object_storage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from temporalio import activity

# ---- DB engine / session ----
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory  # noqa: PLW0603
    if _session_factory is None:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinelrag",
        )
        _engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=5)
        _session_factory = async_sessionmaker(
            bind=_engine, expire_on_commit=False, autoflush=False
        )
    return _session_factory


@asynccontextmanager
async def _session_for_tenant(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield session


# ---- Object storage ----
def _build_storage() -> ObjectStorage:
    return build_object_storage(
        provider=os.environ.get("OBJECT_STORAGE_PROVIDER", "minio"),
        bucket=os.environ.get("OBJECT_STORAGE_BUCKET_DOCUMENTS", "sentinelrag-documents"),
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        endpoint=os.environ.get("OBJECT_STORAGE_ENDPOINT"),
        access_key=os.environ.get("OBJECT_STORAGE_ACCESS_KEY"),
        secret_key=os.environ.get("OBJECT_STORAGE_SECRET_KEY"),
        verify_ssl=False,
    )


# Helper: activities receive UUIDs serialized as strings from the workflow
# (the IngestionWorkflowInput contract dumped to JSON). Accept either.
def _as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


# ---- Activities ----
@activity.defn
async def mark_job_running(job_id: str, tenant_id: str) -> None:
    tid = _as_uuid(tenant_id)
    async with _session_for_tenant(tid) as session:
        await session.execute(
            text(
                "UPDATE ingestion_jobs SET status='running', started_at=now() "
                "WHERE id=:id"
            ),
            {"id": str(_as_uuid(job_id))},
        )


@activity.defn
async def mark_job_failed(job_id: str, tenant_id: str, error: str) -> None:
    tid = _as_uuid(tenant_id)
    async with _session_for_tenant(tid) as session:
        await session.execute(
            text(
                "UPDATE ingestion_jobs "
                "SET status='failed', error_message=:err, completed_at=now() "
                "WHERE id=:id"
            ),
            {"id": str(_as_uuid(job_id)), "err": error},
        )


@activity.defn
async def download_and_hash(tenant_id: str, storage_uri: str) -> dict[str, str]:
    """Download the blob and return its SHA-256.

    Idempotent: rerunning produces the same hash.
    """
    del tenant_id  # not needed for the read; storage_uri is fully qualified
    storage = _build_storage()
    try:
        data = await storage.get(storage_uri)
    finally:
        await storage.close()
    return {
        "content_hash": hashlib.sha256(data).hexdigest(),
        "size_bytes": str(len(data)),
    }


@activity.defn
async def upsert_document_version(
    tenant_id: str,
    document_id: str,
    content_hash: str,
    storage_uri: str,
) -> str:
    """Insert a new document_version OR return the existing one for this hash."""
    tid = _as_uuid(tenant_id)
    did = _as_uuid(document_id)
    async with _session_for_tenant(tid) as session:
        existing = await session.execute(
            text(
                "SELECT id FROM document_versions "
                "WHERE document_id=:did AND content_hash=:h"
            ),
            {"did": str(did), "h": content_hash},
        )
        row = existing.first()
        if row is not None:
            return str(row[0])

        max_v = await session.execute(
            text(
                "SELECT COALESCE(MAX(version_number), 0) FROM document_versions "
                "WHERE document_id=:did"
            ),
            {"did": str(did)},
        )
        next_version = int(max_v.scalar_one()) + 1

        result = await session.execute(
            text(
                "INSERT INTO document_versions "
                "(tenant_id, document_id, version_number, content_hash, storage_uri) "
                "VALUES (:tid, :did, :v, :h, :uri) RETURNING id"
            ),
            {
                "tid": str(tid),
                "did": str(did),
                "v": next_version,
                "h": content_hash,
                "uri": storage_uri,
            },
        )
        return str(result.scalar_one())


@activity.defn
async def parse_document(
    storage_uri: str, mime_type: str, tenant_id: str
) -> dict[str, str]:
    """Parse the blob and persist the ParsedElement list to a temp pickle.

    The next activity (chunk_and_persist) reads from this temp file. We use a
    tempfile (not the DB or object storage) because parsed elements can be
    large and are intermediate-only — discarded after chunking.
    """
    # Lazy import: parser deps are heavy.
    from sentinelrag_shared.parsing import UnstructuredParser  # noqa: PLC0415

    storage = _build_storage()
    try:
        data = await storage.get(storage_uri)
    finally:
        await storage.close()

    parser = UnstructuredParser(strategy="fast")
    elements = list(parser.parse(blob=data, mime_type=mime_type))

    # Persist to a temp file scoped to this activity attempt; the next
    # activity reads it. If the next activity is retried, it re-fetches
    # using the same path (Temporal includes the attempt token in the
    # activity context).
    fd, path = tempfile.mkstemp(prefix="sr-parse-", suffix=".pkl")
    os.close(fd)
    with open(path, "wb") as f:
        pickle.dump(elements, f)
    del tenant_id  # signature kept for audit / future per-tenant temp-dir routing
    return {"elements_path": path, "element_count": str(len(elements))}


@activity.defn
async def chunk_and_persist(
    tenant_id: str,
    document_id: str,
    version_id: str,
    elements_path: str,
    chunking_strategy: str,
) -> int:
    """Read parsed elements, chunk, persist DocumentChunk rows.

    Idempotent on (document_version_id, chunk_index) — re-running deletes
    the previous chunks for this version first.
    """
    from sentinelrag_shared.chunking import ChunkingStrategy, get_chunker  # noqa: PLC0415

    tid = _as_uuid(tenant_id)
    did = _as_uuid(document_id)
    vid = _as_uuid(version_id)

    with open(elements_path, "rb") as f:
        elements = pickle.load(f)  # noqa: S301
    with contextlib.suppress(OSError):
        os.unlink(elements_path)

    chunker = get_chunker(ChunkingStrategy(chunking_strategy))
    chunks = chunker.chunk(elements)

    async with _session_for_tenant(tid) as session:
        await session.execute(
            text("DELETE FROM document_chunks WHERE document_version_id=:vid"),
            {"vid": str(vid)},
        )
        for chunk in chunks:
            await session.execute(
                text(
                    "INSERT INTO document_chunks "
                    "(tenant_id, document_id, document_version_id, chunk_index, "
                    " content, token_count, page_number, section_title, metadata) "
                    "VALUES (:tid, :did, :vid, :idx, :content, :tokens, "
                    "        :page, :section, CAST(:meta AS jsonb))"
                ),
                {
                    "tid": str(tid),
                    "did": str(did),
                    "vid": str(vid),
                    "idx": chunk.chunk_index,
                    "content": chunk.text,
                    "tokens": chunk.token_count,
                    "page": chunk.page_number,
                    "section": chunk.section_title,
                    "meta": json.dumps(chunk.metadata),
                },
            )
    return len(chunks)


@activity.defn
async def embed_chunks(
    tenant_id: str, version_id: str, embedding_model: str
) -> int:
    """Embed all chunks for the given version and persist chunk_embeddings."""
    from sentinelrag_shared.llm import LiteLLMEmbedder  # noqa: PLC0415

    tid = _as_uuid(tenant_id)
    vid = _as_uuid(version_id)

    embedder = LiteLLMEmbedder(
        model_name=embedding_model,
        api_base=os.environ.get("OLLAMA_BASE_URL")
        if embedding_model.startswith("ollama/")
        else None,
    )
    dim = embedder.dimension
    if dim not in {768, 1024, 1536}:
        raise ValueError(f"Unsupported embedding dimension: {dim}")
    column = f"embedding_{dim}"

    async with _session_for_tenant(tid) as session:
        # Idempotency wipe.
        await session.execute(
            text(
                "DELETE FROM chunk_embeddings ce USING document_chunks dc "
                "WHERE ce.chunk_id=dc.id AND dc.document_version_id=:vid "
                "  AND ce.embedding_model=:model"
            ),
            {"vid": str(vid), "model": embedding_model},
        )

        rows = (
            await session.execute(
                text(
                    "SELECT id, content FROM document_chunks "
                    "WHERE document_version_id=:vid ORDER BY chunk_index"
                ),
                {"vid": str(vid)},
            )
        ).fetchall()

    chunk_ids = [r[0] for r in rows]
    contents = [r[1] for r in rows]
    if not contents:
        return 0

    result = await embedder.embed(contents)

    # `column` is allowlisted to embedding_{768,1024,1536} above.
    insert_sql = (
        f"INSERT INTO chunk_embeddings "  # noqa: S608
        f"(tenant_id, chunk_id, embedding_model, {column}) "
        f"VALUES (:tid, :cid, :model, CAST(:vec AS vector))"
    )
    async with _session_for_tenant(tid) as session:
        for chunk_id, vec in zip(chunk_ids, result.vectors, strict=True):
            await session.execute(
                text(insert_sql),
                {
                    "tid": str(tid),
                    "cid": str(chunk_id),
                    "model": embedding_model,
                    "vec": _format_vector(vec),
                },
            )
    return len(chunk_ids)


def _format_vector(vec: list[float]) -> str:
    """Format a Python list as a pgvector literal: '[v1,v2,...]'."""
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


@activity.defn
async def finalize_document(
    job_id: str,
    tenant_id: str,
    document_id: str,
    chunks_created: int,
) -> None:
    tid = _as_uuid(tenant_id)
    did = _as_uuid(document_id)
    jid = _as_uuid(job_id)
    async with _session_for_tenant(tid) as session:
        await session.execute(
            text("UPDATE documents SET status='indexed' WHERE id=:did"),
            {"did": str(did)},
        )
        await session.execute(
            text(
                "UPDATE ingestion_jobs "
                "SET status='completed', completed_at=now(), "
                "    documents_processed=documents_processed+1, "
                "    chunks_created=chunks_created+:chunks "
                "WHERE id=:id"
            ),
            {"id": str(jid), "chunks": chunks_created},
        )
    del did  # silenced: kept in signature for explicit doc/audit linkage


# Used by the worker entrypoint to register all activities.
ALL_ACTIVITIES: list[Any] = [
    mark_job_running,
    mark_job_failed,
    download_and_hash,
    upsert_document_version,
    parse_document,
    chunk_and_persist,
    embed_chunks,
    finalize_document,
]
