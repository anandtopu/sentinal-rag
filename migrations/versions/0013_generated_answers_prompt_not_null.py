"""Require generated answers to reference prompt versions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        WITH tenants_need AS (
            SELECT DISTINCT tenant_id
            FROM generated_answers
            WHERE prompt_version_id IS NULL
        )
        INSERT INTO prompt_templates (
            tenant_id, name, description, task_type, status, created_by
        )
        SELECT
            tn.tenant_id,
            'rag_answer_generation',
            'Seeded default prompt for grounded RAG answer generation.',
            'rag_answer_generation',
            'active',
            NULL
        FROM tenants_need tn
        WHERE NOT EXISTS (
            SELECT 1
            FROM prompt_templates pt
            WHERE pt.tenant_id = tn.tenant_id
              AND pt.name = 'rag_answer_generation'
        )
    """)
    op.execute("""
        WITH tenants_need AS (
            SELECT DISTINCT tenant_id
            FROM generated_answers
            WHERE prompt_version_id IS NULL
        ),
        templates AS (
            SELECT pt.id, pt.tenant_id
            FROM prompt_templates pt
            JOIN tenants_need tn ON tn.tenant_id = pt.tenant_id
            WHERE pt.name = 'rag_answer_generation'
        )
        INSERT INTO prompt_versions (
            tenant_id,
            prompt_template_id,
            version_number,
            system_prompt,
            user_prompt_template,
            parameters,
            model_config,
            is_default,
            created_by
        )
        SELECT
            t.tenant_id,
            t.id,
            COALESCE((
                SELECT max(pv.version_number) + 1
                FROM prompt_versions pv
                WHERE pv.prompt_template_id = t.id
            ), 1),
            $prompt$
You are SentinelRAG, an enterprise assistant. Answer ONLY from the provided context. If the context does not contain enough information, say you do not have enough information rather than guessing. Cite supporting passages inline using [1], [2], etc. corresponding to the numbered Context entries.
$prompt$,
            $prompt$
Question: {query}

Context:
{context}

Answer using the context above. Include citation markers like [1], [2] for each claim. If the context is insufficient, say so.
$prompt$,
            '{}'::jsonb,
            '{}'::jsonb,
            true,
            NULL
        FROM templates t
        WHERE NOT EXISTS (
            SELECT 1
            FROM prompt_versions pv
            WHERE pv.prompt_template_id = t.id
              AND pv.is_default = true
        )
    """)
    op.execute("""
        UPDATE generated_answers ga
        SET prompt_version_id = pv.id
        FROM prompt_templates pt
        JOIN prompt_versions pv
          ON pv.prompt_template_id = pt.id
         AND pv.is_default = true
        WHERE ga.prompt_version_id IS NULL
          AND pt.tenant_id = ga.tenant_id
          AND pt.name = 'rag_answer_generation'
    """)
    op.execute(
        "ALTER TABLE generated_answers ALTER COLUMN prompt_version_id SET NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE generated_answers ALTER COLUMN prompt_version_id DROP NOT NULL"
    )
