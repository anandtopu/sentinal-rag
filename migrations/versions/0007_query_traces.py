"""Query sessions, retrieval results, generated answers, citations.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26

Implements Enterprise_RAG_Database_Design.md sections 8.1-8.4.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE query_sessions (
            id                UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id         UUID            NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id           UUID            REFERENCES users(id),
            query_text        TEXT            NOT NULL,
            normalized_query  TEXT,
            collection_ids    UUID[]          NOT NULL,
            status            TEXT            NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'failed', 'abstained')),
            latency_ms        INT,
            total_cost_usd    NUMERIC(12, 6)  NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ     NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_query_sessions_tenant_user "
        "ON query_sessions(tenant_id, user_id)"
    )
    op.execute(
        "CREATE INDEX idx_query_sessions_created_at " "ON query_sessions(created_at)"
    )

    op.execute("""
        CREATE TABLE retrieval_results (
            id                UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id         UUID              NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            query_session_id  UUID              NOT NULL REFERENCES query_sessions(id) ON DELETE CASCADE,
            chunk_id          UUID              NOT NULL REFERENCES document_chunks(id),
            retrieval_stage   TEXT              NOT NULL
                CHECK (retrieval_stage IN ('bm25', 'vector', 'hybrid_merge', 'rerank')),
            rank              INT               NOT NULL,
            score             DOUBLE PRECISION  NOT NULL,
            metadata          JSONB             NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ       NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_retrieval_results_session "
        "ON retrieval_results(query_session_id)"
    )
    op.execute(
        "CREATE INDEX idx_retrieval_results_chunk " "ON retrieval_results(chunk_id)"
    )

    op.execute("""
        CREATE TABLE generated_answers (
            id                         UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id                  UUID              NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            query_session_id           UUID              NOT NULL REFERENCES query_sessions(id) ON DELETE CASCADE,
            answer_text                TEXT              NOT NULL,
            model_provider             TEXT              NOT NULL,
            model_name                 TEXT              NOT NULL,
            prompt_version_id          UUID              REFERENCES prompt_versions(id),
            input_tokens               INT,
            output_tokens              INT,
            cost_usd                   NUMERIC(12, 6),
            confidence_score           DOUBLE PRECISION,
            hallucination_risk_score   DOUBLE PRECISION,
            grounding_score            DOUBLE PRECISION,
            judge_reasoning            TEXT,
            created_at                 TIMESTAMPTZ       NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_generated_answers_session "
        "ON generated_answers(query_session_id)"
    )

    op.execute("""
        CREATE TABLE answer_citations (
            id                   UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id            UUID              NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            generated_answer_id  UUID              NOT NULL REFERENCES generated_answers(id) ON DELETE CASCADE,
            chunk_id             UUID              NOT NULL REFERENCES document_chunks(id),
            citation_index       INT               NOT NULL,
            quoted_text          TEXT,
            relevance_score      DOUBLE PRECISION,
            created_at           TIMESTAMPTZ       NOT NULL DEFAULT now(),

            UNIQUE (generated_answer_id, citation_index)
        )
    """)
    op.execute(
        "CREATE INDEX idx_answer_citations_answer "
        "ON answer_citations(generated_answer_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS answer_citations CASCADE")
    op.execute("DROP TABLE IF EXISTS generated_answers CASCADE")
    op.execute("DROP TABLE IF EXISTS retrieval_results CASCADE")
    op.execute("DROP TABLE IF EXISTS query_sessions CASCADE")
