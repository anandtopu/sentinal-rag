"""Document + ingestion service.

Coordinates the document upload lifecycle:
    1. Hash the upload to compute a content checksum.
    2. Insert / fetch the ``Document`` row (idempotent on tenant + checksum).
    3. Write the blob to object storage at a deterministic key.
    4. Create an ``IngestionJob`` row.
    5. Start the Temporal ``IngestionWorkflow`` and persist its workflow_id.

Idempotency rule: re-uploading the same content (same SHA-256) returns the
existing document and skips re-ingestion if the document is already
``indexed``. Tenants who legitimately want to re-ingest can append a
``?force_reindex=true`` query (Phase 2.5+).
"""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sentinelrag_shared.contracts import IngestionWorkflowInput
from sentinelrag_shared.errors.exceptions import NotFoundError
from sentinelrag_shared.object_storage import ObjectStorage
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client as TemporalClient

from app.db.models import Document, IngestionJob
from app.db.repositories import (
    CollectionRepository,
    DocumentRepository,
    IngestionJobRepository,
)
from app.schemas.documents import DocumentCreate


class DocumentService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        storage: ObjectStorage,
        temporal_client: TemporalClient,
        ingestion_task_queue: str,
        default_embedding_model: str,
    ) -> None:
        self.db = db
        self.storage = storage
        self.temporal = temporal_client
        self.ingestion_task_queue = ingestion_task_queue
        self.default_embedding_model = default_embedding_model

        self.docs = DocumentRepository(db)
        self.collections = CollectionRepository(db)
        self.jobs = IngestionJobRepository(db)

    async def upload(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID,
        payload: DocumentCreate,
        filename: str,
        mime_type: str,
        body: bytes,
    ) -> tuple[Document, IngestionJob]:
        # Verify the collection exists in this tenant (RLS enforces tenancy).
        collection = await self.collections.get(payload.collection_id)
        if collection is None:
            raise NotFoundError("Collection not found.")

        checksum = hashlib.sha256(body).hexdigest()

        # Idempotency: same checksum within the tenant → return the existing doc.
        existing = await self.docs.get_by_checksum(tenant_id=tenant_id, checksum=checksum)
        if existing is not None and existing.status == "indexed":
            # Return a no-op job pointer for API consistency.
            existing_job = IngestionJob(
                tenant_id=tenant_id,
                collection_id=payload.collection_id,
                status="completed",
                input_source={"deduplicated": True, "document_id": str(existing.id)},
                chunking_strategy="semantic",
                embedding_model=self.default_embedding_model,
                created_by=created_by,
            )
            self.db.add(existing_job)
            await self.db.flush()
            return existing, existing_job

        # Storage key follows the convention from ADR-0015.
        document_id = uuid4()
        version_token = uuid4().hex[:12]
        storage_key = (
            f"{tenant_id}/documents/{document_id}/versions/{version_token}/"
            f"original.{_extension_for(mime_type, filename)}"
        )
        await self.storage.put(
            storage_key,
            body,
            content_type=mime_type,
            custom_metadata={
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
            },
        )

        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            collection_id=payload.collection_id,
            title=payload.title or filename,
            source_type="upload",
            source_uri=storage_key,
            mime_type=mime_type,
            checksum=checksum,
            sensitivity_level=payload.sensitivity_level,
            metadata_=payload.metadata,
            status="pending",
            created_by=created_by,
        )
        self.db.add(document)

        job = IngestionJob(
            tenant_id=tenant_id,
            collection_id=payload.collection_id,
            status="queued",
            input_source={
                "type": "upload",
                "document_id": str(document_id),
                "storage_uri": storage_key,
                "mime_type": mime_type,
            },
            chunking_strategy="semantic",
            embedding_model=self.default_embedding_model,
            created_by=created_by,
        )
        self.db.add(job)
        await self.db.flush()

        # Kick off the Temporal workflow; persist the workflow_id for status polling.
        # Import locally to avoid a heavy import in the route module.
        workflow_id = await self._start_ingestion_workflow(
            job_id=job.id,
            tenant_id=tenant_id,
            collection_id=payload.collection_id,
            document_id=document.id,
            storage_uri=storage_key,
            mime_type=mime_type,
            chunking_strategy="semantic",
            embedding_model=self.default_embedding_model,
            metadata=payload.metadata,
        )
        job.workflow_id = workflow_id
        await self.db.flush()

        return document, job

    async def _start_ingestion_workflow(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
        collection_id: UUID,
        document_id: UUID,
        storage_uri: str,
        mime_type: str,
        chunking_strategy: str,
        embedding_model: str,
        metadata: dict,
    ) -> str:
        # Typed contract from sentinelrag_shared.contracts. Both API service and
        # temporal-worker import from the same package — no field drift.
        payload = IngestionWorkflowInput(
            job_id=job_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            storage_uri=storage_uri,
            mime_type=mime_type,
            chunking_strategy=chunking_strategy,
            embedding_model=embedding_model,
            metadata=metadata,
        )
        workflow_id = f"ingest-{job_id}"
        await self.temporal.start_workflow(
            "IngestionWorkflow",
            payload.model_dump(mode="json"),
            id=workflow_id,
            task_queue=self.ingestion_task_queue,
        )
        return workflow_id


_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/csv": "csv",
}


def _extension_for(mime_type: str, filename: str) -> str:
    if mime_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime_type]
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return "bin"
