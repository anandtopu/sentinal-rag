"""Multi-dimension embeddings on chunk_embeddings.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-26

Implements ADR-0020. Replaces the single ``embedding vector(1536)`` column
with three nullable per-dimension columns (768/1024/1536), a CHECK
constraint enforcing exactly one is non-NULL, and an HNSW index per column.

Safe to apply on an empty table (which is the case at this point in
migration history). On a populated table, the column drop loses data; we
accept that here because Phase 2 hasn't ingested anything yet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old single-dimension index and column.
    op.execute("DROP INDEX IF EXISTS idx_chunk_embeddings_vector")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding")

    # Per-dimension columns. NULLABLE; CHECK enforces exactly one is set.
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding_768  vector(768)")
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding_1024 vector(1024)")
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding_1536 vector(1536)")

    op.execute("""
        ALTER TABLE chunk_embeddings ADD CONSTRAINT ck_chunk_embeddings_one_dim
            CHECK (
                (embedding_768  IS NOT NULL)::int +
                (embedding_1024 IS NOT NULL)::int +
                (embedding_1536 IS NOT NULL)::int = 1
            )
    """)

    # One HNSW index per dim column. Each is built only over the non-NULL rows
    # because pgvector's HNSW skips NULLs; the predicate is implicit.
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_vec_768 "
        "ON chunk_embeddings USING hnsw (embedding_768 vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_vec_1024 "
        "ON chunk_embeddings USING hnsw (embedding_1024 vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_vec_1536 "
        "ON chunk_embeddings USING hnsw (embedding_1536 vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunk_embeddings_vec_1536")
    op.execute("DROP INDEX IF EXISTS idx_chunk_embeddings_vec_1024")
    op.execute("DROP INDEX IF EXISTS idx_chunk_embeddings_vec_768")
    op.execute(
        "ALTER TABLE chunk_embeddings DROP CONSTRAINT IF EXISTS ck_chunk_embeddings_one_dim"
    )
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding_768")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding_1024")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding_1536")

    # Restore the original single-dim column + index.
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.execute(
        "CREATE INDEX idx_chunk_embeddings_vector "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
