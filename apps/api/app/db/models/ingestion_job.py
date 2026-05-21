"""IngestionJob ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'queued'")
    )
    input_source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    chunking_strategy: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'semantic'")
    )
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    documents_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    documents_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    chunks_created: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
