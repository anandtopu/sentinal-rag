"""Add error_message column to query_sessions.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-16

Background (R1.S3): the orchestrator previously concatenated failed-query
error messages onto ``normalized_query`` because no dedicated column
existed. That polluted the column used for query analytics / future
cache keys. This migration adds a real ``error_message`` column.

No backfill: legacy rows keep their polluted ``normalized_query``;
new failed rows get the structured column. The orchestrator switches to
the new column in the same R1.S3 PR.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE query_sessions
            ADD COLUMN error_message TEXT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE query_sessions
            DROP COLUMN error_message
    """)
