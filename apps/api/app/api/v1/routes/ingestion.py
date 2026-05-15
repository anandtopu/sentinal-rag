"""Ingestion job routes — read + list status."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors.exceptions import NotFoundError, TemporalUnavailableError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.models import IngestionJob
from app.db.repositories import IngestionJobRepository
from app.db.session import get_db
from app.dependencies import TemporalClientDep
from app.schemas.documents import IngestionJobRead

router = APIRouter(prefix="/ingestion/jobs", tags=["ingestion"])


@router.get("/{job_id}", response_model=IngestionJobRead)
async def read_job(
    job_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("documents:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionJobRead:
    repo = IngestionJobRepository(db)
    job = await repo.get(job_id)
    if job is None:
        raise NotFoundError("Ingestion job not found.")
    return _read_model(job)


@router.post("/{job_id}/cancel", response_model=IngestionJobRead)
async def cancel_job(
    job_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("documents:write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    temporal: TemporalClientDep,
) -> IngestionJobRead:
    repo = IngestionJobRepository(db)
    job = await repo.get(job_id)
    if job is None:
        raise NotFoundError("Ingestion job not found.")

    should_cancel = job.status not in {"completed", "failed", "cancelled"}
    if should_cancel and job.workflow_id:
        try:
            await temporal.get_workflow_handle(job.workflow_id).cancel()
        except Exception as exc:
            raise TemporalUnavailableError(
                "Temporal is unavailable; ingestion job was not cancelled."
            ) from exc

    if should_cancel:
        await db.execute(
            text(
                "UPDATE ingestion_jobs "
                "SET status='cancelled', completed_at=now() "
                "WHERE id=:id AND status NOT IN ('completed', 'failed', 'cancelled')"
            ),
            {"id": str(job_id)},
        )
        document_id = job.input_source.get("document_id")
        if isinstance(document_id, str):
            await db.execute(
                text("UPDATE documents SET status='failed' WHERE id=:id"),
                {"id": document_id},
            )
    await db.refresh(job)
    return _read_model(job)


@router.get("", response_model=list[IngestionJobRead])
async def list_jobs(
    _ctx: Annotated[AuthContext, Depends(require_permission("documents:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    collection_id: Annotated[UUID, Query(...)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IngestionJobRead]:
    repo = IngestionJobRepository(db)
    items = await repo.list_for_collection(collection_id, limit=limit, offset=offset)
    return [_read_model(j) for j in items]


def _read_model(job: IngestionJob) -> IngestionJobRead:
    return IngestionJobRead.model_validate(
        {
            "id": job.id,
            "tenant_id": job.tenant_id,
            "collection_id": job.collection_id,
            "status": job.status,
            "chunking_strategy": job.chunking_strategy,
            "embedding_model": job.embedding_model,
            "documents_total": job.documents_total,
            "documents_processed": job.documents_processed,
            "chunks_created": job.chunks_created,
            "error_message": job.error_message,
            "workflow_id": job.workflow_id,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
        }
    )
