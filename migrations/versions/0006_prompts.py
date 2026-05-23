"""Prompt templates and versions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26

Implements Enterprise_RAG_Database_Design.md sections 7.1-7.2.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE prompt_templates (
            id          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id   UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name        TEXT         NOT NULL,
            description TEXT,
            task_type   TEXT         NOT NULL,
            status      TEXT         NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived')),
            created_by  UUID         REFERENCES users(id),
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

            UNIQUE (tenant_id, name)
        )
    """)
    op.execute(
        "CREATE INDEX idx_prompt_templates_tenant_id " "ON prompt_templates(tenant_id)"
    )

    op.execute("""
        CREATE TABLE prompt_versions (
            id                    UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id             UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            prompt_template_id    UUID         NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
            version_number        INT          NOT NULL,
            system_prompt         TEXT         NOT NULL,
            user_prompt_template  TEXT         NOT NULL,
            parameters            JSONB        NOT NULL DEFAULT '{}'::jsonb,
            model_config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
            is_default            BOOLEAN      NOT NULL DEFAULT false,
            created_by            UUID         REFERENCES users(id),
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

            UNIQUE (prompt_template_id, version_number)
        )
    """)
    # At most one default version per template, enforced by partial unique index.
    op.execute(
        "CREATE UNIQUE INDEX idx_prompt_versions_default "
        "ON prompt_versions(prompt_template_id) WHERE is_default = true"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS prompt_templates CASCADE")
