"""Document routes — upload + read + list."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors.exceptions import NotFoundError, ValidationFailedError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.core.config import get_settings
from app.db.repositories import DocumentRepository
from app.db.session import get_db
from app.dependencies import ObjectStorageDep, TemporalClientDep
from app.schemas.common import Page
from app.schemas.documents import (
    DocumentCreate,
    DocumentRead,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB hard cap (raise via Helm value later)


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    ctx: Annotated[AuthContext, Depends(require_permission("documents:write"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: ObjectStorageDep,
    temporal: TemporalClientDep,
    collection_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    sensitivity_level: Annotated[str, Form()] = "internal",
    metadata: Annotated[str, Form()] = "{}",
) -> DocumentUploadResponse:
    body = await file.read()
    if not body:
        raise ValidationFailedError("Uploaded file is empty.")
    if len(body) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload too large.")

    try:
        meta_dict: dict[str, Any] = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError as exc:
        raise ValidationFailedError("metadata must be JSON.") from exc

    payload = DocumentCreate(
        collection_id=collection_id,
        title=title,
        sensitivity_level=sensitivity_level,
        metadata=meta_dict,
    )

    settings = get_settings()
    service = DocumentService(
        db,
        storage=storage,
        temporal_client=temporal,
        ingestion_task_queue=settings.temporal_task_queue_ingestion,
        default_embedding_model=settings.default_embedding_model,
    )
    document, job = await service.upload(
        tenant_id=ctx.tenant_id,
        created_by=ctx.user_id,
        payload=payload,
        filename=file.filename or "unnamed",
        mime_type=file.content_type or "application/octet-stream",
        body=body,
    )
    return DocumentUploadResponse(
        document_id=document.id,
        status=document.status,
        ingestion_job_id=job.id,
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("documents:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentRead:
    repo = DocumentRepository(db)
    document = await repo.get(document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return DocumentRead.model_validate(document)


@router.get("", response_model=Page[DocumentRead])
async def list_documents(
    _ctx: Annotated[AuthContext, Depends(require_permission("documents:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    collection_id: Annotated[UUID, Query(...)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DocumentRead]:
    repo = DocumentRepository(db)
    items = await repo.list_for_collection(collection_id, limit=limit, offset=offset)
    total = await repo.count_for_collection(collection_id)
    return Page[DocumentRead](
        items=[DocumentRead.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )
