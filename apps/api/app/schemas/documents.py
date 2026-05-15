"""Pydantic schemas for documents + ingestion API I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel, FullTimestampedRead


class DocumentCreate(APIModel):
    """Form-data multipart upload metadata.

    The actual file bytes come in via the multipart ``file`` field on the
    route handler; this schema captures only the JSON metadata.
    """

    collection_id: UUID
    title: str | None = Field(default=None, max_length=500)
    sensitivity_level: Literal["public", "internal", "confidential", "restricted"] = "internal"
    chunking_strategy: Literal["semantic", "sliding_window", "structure_aware"] = "semantic"
    parsing_strategy: Literal["fast", "hi_res", "ocr_only", "auto"] = "fast"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRead(FullTimestampedRead):
    id: UUID
    tenant_id: UUID
    collection_id: UUID
    title: str
    source_type: str
    source_uri: str | None
    mime_type: str | None
    sensitivity_level: str
    status: str
    metadata: dict[str, Any] = Field(alias="metadata_")


class DocumentUploadResponse(APIModel):
    document_id: UUID
    status: str
    ingestion_job_id: UUID


class IngestionJobCreate(APIModel):
    collection_id: UUID
    source: dict[str, Any]
    chunking_strategy: str = Field(default="semantic")
    embedding_model: str = Field(default="ollama/nomic-embed-text")


class IngestionJobRead(APIModel):
    id: UUID
    tenant_id: UUID
    collection_id: UUID
    status: str
    chunking_strategy: str
    embedding_model: str
    documents_total: int
    documents_processed: int
    chunks_created: int
    error_message: str | None
    workflow_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
