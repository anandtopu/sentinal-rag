"""Ingestion job routes — read + list status."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors.exceptions import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.repositories import IngestionJobRepository
from app.db.session import get_db
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
    return [
        IngestionJobRead.model_validate(
            {
                "id": j.id,
                "tenant_id": j.tenant_id,
                "collection_id": j.collection_id,
                "status": j.status,
                "chunking_strategy": j.chunking_strategy,
                "embedding_model": j.embedding_model,
                "documents_total": j.documents_total,
                "documents_processed": j.documents_processed,
                "chunks_created": j.chunks_created,
                "error_message": j.error_message,
                "workflow_id": j.workflow_id,
                "started_at": j.started_at,
                "completed_at": j.completed_at,
                "created_at": j.created_at,
            }
        )
        for j in items
    ]
