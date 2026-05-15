"""Track per-case eval status and make scores idempotent.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE evaluation_scores
            ADD COLUMN status TEXT NOT NULL DEFAULT 'completed',
            ADD COLUMN error_message TEXT,
            ADD CONSTRAINT ck_evaluation_scores_status
                CHECK (status IN ('completed', 'failed', 'skipped'))
    """)
    op.execute("""
        DELETE FROM evaluation_scores es
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY evaluation_run_id, evaluation_case_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM evaluation_scores
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE es.id = dupes.id
    """)
    op.execute("""
        ALTER TABLE evaluation_scores
            ADD CONSTRAINT uq_eval_scores_run_case
                UNIQUE (evaluation_run_id, evaluation_case_id)
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE evaluation_scores "
        "DROP CONSTRAINT IF EXISTS uq_eval_scores_run_case"
    )
    op.execute(
        "ALTER TABLE evaluation_scores "
        "DROP CONSTRAINT IF EXISTS ck_evaluation_scores_status"
    )
    op.execute(
        "ALTER TABLE evaluation_scores "
        "DROP COLUMN IF EXISTS error_message, "
        "DROP COLUMN IF EXISTS status"
    )
