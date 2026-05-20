"""Composite index query_sessions(tenant_id, created_at DESC).

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-20

Background: the per-tenant read-models added for the v0.6 console scan
``query_sessions`` filtered by tenant (the RLS policy adds a ``tenant_id``
predicate) over a ``created_at`` window, and the query-history feed orders by
``created_at DESC`` (ADR-0038 metrics summary, BACKLOG B10 #1/#3). The table
already had ``(tenant_id, user_id)`` and ``(created_at)`` indexes but no
composite covering the ``(tenant_id, created_at)`` access path, so those scans
read wider than necessary. ADR-0038 recorded this index as a follow-up.

Migration class A (additive, safe) per ADR-0033. The index is built
``CONCURRENTLY`` so it takes only a SHARE UPDATE EXCLUSIVE lock and never
blocks concurrent reads/writes on a live table. ``CREATE INDEX CONCURRENTLY``
cannot run inside a transaction, and ``migrations/env.py`` runs each revision
with ``transaction_per_migration=True`` — so the statement runs inside an
``autocommit_block``. No ``statement_timeout`` cap is imposed here: a
concurrent build holds no blocking lock, so a long build is safe and must not
be aborted mid-way (the 5-minute cap in ADR-0033 is for blocking DDL).

``DESC`` matches the query-history ``ORDER BY created_at DESC`` exactly; it
also serves the metrics range scan (a btree range scan is direction-agnostic).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_query_sessions_tenant_created "
            "ON query_sessions (tenant_id, created_at DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_query_sessions_tenant_created")
