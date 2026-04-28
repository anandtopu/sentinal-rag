"""Ingestion workflow contracts (API → temporal-worker)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from sentinelrag_shared.contracts.base import Contract


class IngestionWorkflowInput(Contract):
    """Input to ``IngestionWorkflow.run``.

    Constructed by the API service's ``DocumentService.upload`` and serialized
    by the Temporal client. Reconstructed inside the worker by the workflow.
    """

    job_id: UUID
    tenant_id: UUID
    collection_id: UUID
    document_id: UUID
    storage_uri: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=1)
    chunking_strategy: str = Field(default="semantic")
    embedding_model: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionWorkflowResult(Contract):
    """Result of a successful ``IngestionWorkflow.run``."""

    job_id: UUID
    document_version_id: UUID
    chunks_created: int = Field(..., ge=0)
