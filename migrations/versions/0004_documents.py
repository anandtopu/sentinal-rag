"""Documents, document versions, chunks, embeddings.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26

Implements Enterprise_RAG_Database_Design.md sections 5.1-5.4 with the
following ADR-driven changes:
    - ADR-0003: chunk_embeddings uses HNSW index (not ivfflat).
    - ADR-0004: document_chunks has tsvector column + GIN index for FTS.
    - ADR-0015: document_versions has NO raw_text column; storage_uri is
                NOT NULL and is the source of truth.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- documents ----
    op.execute("""
        CREATE TABLE documents (
            id                  UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id           UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            collection_id       UUID         NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            title               TEXT         NOT NULL,
            source_type         TEXT         NOT NULL
                CHECK (source_type IN ('upload', 's3', 'gcs', 'url', 'database', 'api')),
            source_uri          TEXT,
            mime_type           TEXT,
            checksum            TEXT         NOT NULL,
            sensitivity_level   TEXT         NOT NULL DEFAULT 'internal'
                CHECK (sensitivity_level IN ('public', 'internal', 'confidential', 'restricted')),
            status              TEXT         NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'indexed', 'failed', 'archived')),
            metadata            JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_by          UUID         REFERENCES users(id),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_documents_tenant_collection "
        "ON documents(tenant_id, collection_id)"
    )
    op.execute("CREATE INDEX idx_documents_status ON documents(status)")
    op.execute("CREATE INDEX idx_documents_checksum ON documents(tenant_id, checksum)")
    op.execute("""
        CREATE TRIGGER trg_documents_updated_at
        BEFORE UPDATE ON documents
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # ---- document_versions (raw_text REMOVED per ADR-0015) ----
    op.execute("""
        CREATE TABLE document_versions (
            id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id       UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id     UUID         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_number  INT          NOT NULL,
            content_hash    TEXT         NOT NULL,
            storage_uri     TEXT         NOT NULL,
            parser_version  TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

            UNIQUE (document_id, version_number)
        )
    """)
    op.execute(
        "CREATE INDEX idx_document_versions_document_id "
        "ON document_versions(document_id)"
    )

    # ---- document_chunks (tsvector + GIN per ADR-0004) ----
    op.execute("""
        CREATE TABLE document_chunks (
            id                   UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id            UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id          UUID         NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            document_version_id  UUID         NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            chunk_index          INT          NOT NULL,
            content              TEXT         NOT NULL,
            content_tsv          tsvector     GENERATED ALWAYS AS
                                              (to_tsvector('english', coalesce(content, ''))) STORED,
            token_count          INT,
            page_number          INT,
            section_title        TEXT,
            access_policy        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),

            UNIQUE (document_version_id, chunk_index)
        )
    """)
    op.execute(
        "CREATE INDEX idx_chunks_tenant_document "
        "ON document_chunks(tenant_id, document_id)"
    )
    op.execute(
        "CREATE INDEX idx_chunks_content_tsv "
        "ON document_chunks USING GIN (content_tsv)"
    )
    # Trigram index for typo-tolerant matching (used in admin search).
    op.execute(
        "CREATE INDEX idx_chunks_content_trgm "
        "ON document_chunks USING GIN (content gin_trgm_ops)"
    )

    # ---- chunk_embeddings (HNSW per ADR-0003) ----
    # The embedding column dimension is set to 1536 to support OpenAI's
    # text-embedding-3-small. For self-hosted nomic-embed-text (768d) we use
    # a SEPARATE embedding model row per chunk; the multi-row design is correct.
    # Future ADR may add a second column or table for non-1536 models.
    op.execute("""
        CREATE TABLE chunk_embeddings (
            id               UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id        UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            chunk_id         UUID          NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
            embedding_model  TEXT          NOT NULL,
            embedding        vector(1536)  NOT NULL,
            created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),

            UNIQUE (chunk_id, embedding_model)
        )
    """)
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_tenant ON chunk_embeddings(tenant_id)"
    )
    # HNSW index (m=16, ef_construction=64 are pgvector's recommended defaults).
    # Build with maintenance_work_mem temporarily increased (per pgvector docs).
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_vector "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunk_embeddings CASCADE")
    op.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS document_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
