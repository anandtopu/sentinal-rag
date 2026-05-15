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

import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

# These imports come from sentinelrag-shared and from the API package which
# defines the ORM models. The Temporal worker container installs both.
from sentinelrag_shared.object_storage import ObjectStorage, build_object_storage
from sentinelrag_shared.parsing import ElementType, ParsedElement
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from temporalio import activity

from sentinelrag_worker.settings import get_database_url

# ---- DB engine / session ----
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory  # noqa: PLW0603
    if _session_factory is None:
        dsn = get_database_url()
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
async def mark_job_running(job_id: str, tenant_id: str, document_id: str) -> None:
    tid = _as_uuid(tenant_id)
    async with _session_for_tenant(tid) as session:
        await session.execute(
            text(
                "UPDATE ingestion_jobs SET status='running', started_at=now() "
                "WHERE id=:id"
            ),
            {"id": str(_as_uuid(job_id))},
        )
        await session.execute(
            text("UPDATE documents SET status='processing' WHERE id=:did"),
            {"did": str(_as_uuid(document_id))},
        )


@activity.defn
async def mark_job_failed(
    job_id: str, tenant_id: str, document_id: str, error: str
) -> None:
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
        await session.execute(
            text("UPDATE documents SET status='failed' WHERE id=:did"),
            {"did": str(_as_uuid(document_id))},
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
    storage_uri: str, mime_type: str, tenant_id: str, parsing_strategy: str = "fast"
) -> dict[str, str]:
    """Parse the blob and persist intermediate outputs to object storage.

    The next activity may run on a different worker pod, so local temp files
    are not durable enough for Temporal activity boundaries.
    """
    # Lazy import: parser deps are heavy.
    from sentinelrag_shared.parsing import UnstructuredParser  # noqa: PLC0415

    storage = _build_storage()
    try:
        data = await storage.get(storage_uri)

        parser = UnstructuredParser(strategy=parsing_strategy)
        elements = list(parser.parse(blob=data, mime_type=mime_type))
        raw_text = "\n\n".join(e.text.strip() for e in elements if e.text.strip())

        raw_text_uri = _raw_text_key(storage_uri)
        elements_uri = _parsed_elements_key(storage_uri)
        await storage.put(
            raw_text_uri,
            raw_text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            custom_metadata={"tenant_id": tenant_id},
        )
        await storage.put(
            elements_uri,
            json.dumps([_element_to_dict(e) for e in elements], default=str).encode(
                "utf-8"
            ),
            content_type="application/json",
            custom_metadata={"tenant_id": tenant_id},
        )
    finally:
        await storage.close()
    return {
        "elements_uri": elements_uri,
        "raw_text_uri": raw_text_uri,
        "element_count": str(len(elements)),
    }


@activity.defn
async def update_document_version_storage_uri(
    tenant_id: str, version_id: str, raw_text_uri: str
) -> None:
    tid = _as_uuid(tenant_id)
    async with _session_for_tenant(tid) as session:
        await session.execute(
            text(
                "UPDATE document_versions "
                "SET storage_uri=:uri, parser_version=:parser "
                "WHERE id=:vid"
            ),
            {
                "vid": str(_as_uuid(version_id)),
                "uri": raw_text_uri,
                "parser": "unstructured",
            },
        )


@activity.defn
async def chunk_and_persist(
    tenant_id: str,
    document_id: str,
    version_id: str,
    elements_uri: str,
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

    storage = _build_storage()
    try:
        raw_elements = json.loads((await storage.get(elements_uri)).decode("utf-8"))
    finally:
        await storage.close()
    elements = [_element_from_dict(item) for item in raw_elements]

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
                "    documents_processed=CASE "
                "        WHEN status='completed' THEN documents_processed "
                "        ELSE LEAST(documents_total, documents_processed+1) "
                "    END, "
                "    chunks_created=:chunks "
                "WHERE id=:id"
            ),
            {"id": str(jid), "chunks": chunks_created},
        )
    del did  # silenced: kept in signature for explicit doc/audit linkage


def _raw_text_key(storage_uri: str) -> str:
    prefix = storage_uri.rsplit("/", 1)[0] if "/" in storage_uri else storage_uri
    return f"{prefix}/raw.txt"


def _parsed_elements_key(storage_uri: str) -> str:
    prefix = storage_uri.rsplit("/", 1)[0] if "/" in storage_uri else storage_uri
    return f"{prefix}/parsed-elements.json"


def _element_to_dict(element: ParsedElement) -> dict[str, Any]:
    return {
        "text": element.text,
        "element_type": element.element_type.value,
        "page_number": element.page_number,
        "section_title": element.section_title,
        "table_html": element.table_html,
        "metadata": element.metadata,
    }


def _element_from_dict(item: dict[str, Any]) -> ParsedElement:
    return ParsedElement(
        text=str(item.get("text") or ""),
        element_type=ElementType(str(item.get("element_type") or ElementType.UNCATEGORIZED)),
        page_number=item.get("page_number") if isinstance(item.get("page_number"), int) else None,
        section_title=item.get("section_title")
        if isinstance(item.get("section_title"), str)
        else None,
        table_html=item.get("table_html") if isinstance(item.get("table_html"), str) else None,
        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
    )


# Used by the worker entrypoint to register all activities.
ALL_ACTIVITIES: list[Any] = [
    mark_job_running,
    mark_job_failed,
    download_and_hash,
    upsert_document_version,
    parse_document,
    update_document_version_storage_uri,
    chunk_and_persist,
    embed_chunks,
    finalize_document,
]
