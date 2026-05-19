"""Add nli_verdict + judge_verdict columns to generated_answers.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-17

Background (R2.S3): the hallucination cascade in ADR-0010 has three
layers; before this revision the only persisted signal was the layer-1
``grounding_score`` (token overlap). The cascade is now wired in
``apps/api/app/services/rag/stages/grounding.py`` and needs durable
per-layer verdict columns so the trace viewer + offline eval can read
the same fields.

The legacy ``judge_reasoning`` column (added in 0007) stays — it carries
the free-form judge rationale; ``judge_verdict`` is the categorical
outcome.

No backfill: legacy rows have NULL verdicts which the cascade interprets
as "layer never ran" (skipped semantics).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE generated_answers
            ADD COLUMN nli_verdict TEXT,
            ADD COLUMN judge_verdict TEXT
    """)
    op.execute("""
        ALTER TABLE generated_answers
            ADD CONSTRAINT chk_generated_answers_nli_verdict
            CHECK (nli_verdict IS NULL
                   OR nli_verdict IN ('entail', 'neutral', 'contradict', 'skipped'))
    """)
    op.execute("""
        ALTER TABLE generated_answers
            ADD CONSTRAINT chk_generated_answers_judge_verdict
            CHECK (judge_verdict IS NULL
                   OR judge_verdict IN ('pass', 'fail', 'skipped'))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE generated_answers
            DROP CONSTRAINT IF EXISTS chk_generated_answers_judge_verdict
    """)
    op.execute("""
        ALTER TABLE generated_answers
            DROP CONSTRAINT IF EXISTS chk_generated_answers_nli_verdict
    """)
    op.execute("""
        ALTER TABLE generated_answers
            DROP COLUMN IF EXISTS judge_verdict,
            DROP COLUMN IF EXISTS nli_verdict
    """)
