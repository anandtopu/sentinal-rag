"""Document, document_version, document_chunk, chunk_embedding repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.db.models import (
    ChunkEmbedding,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.db.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def get_by_checksum(
        self, *, tenant_id: UUID, checksum: str
    ) -> Document | None:
        stmt = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.checksum == checksum,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_collection(
        self,
        collection_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.collection_id == collection_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_collection(self, collection_id: UUID) -> int:
        stmt = select(func.count(Document.id)).where(
            Document.collection_id == collection_id
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class DocumentVersionRepository(BaseRepository[DocumentVersion]):
    model = DocumentVersion

    async def latest_version_number(self, document_id: UUID) -> int:
        stmt = select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
        result = await self.session.execute(stmt)
        max_version = result.scalar_one()
        return int(max_version) if max_version else 0


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    model = DocumentChunk

    async def add_many(self, chunks: list[DocumentChunk]) -> None:
        self.session.add_all(chunks)
        await self.session.flush()


class ChunkEmbeddingRepository(BaseRepository[ChunkEmbedding]):
    model = ChunkEmbedding

    async def add_many(self, embeddings: list[ChunkEmbedding]) -> None:
        self.session.add_all(embeddings)
        await self.session.flush()
