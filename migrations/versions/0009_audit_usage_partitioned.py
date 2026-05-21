"""Audit events + usage records, monthly-partitioned.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-26

Implements Enterprise_RAG_Database_Design.md sections 10.1-10.2 + §11.

Both tables are HIGH-VOLUME and partitioned by month using PostgreSQL native
partitioning. We create the parent table + the first 6 months of partitions
inline; a maintenance job (added in Phase 6) creates future partitions ahead
of time. Without future partitions, INSERTs into a missing range will fail
with an unfriendly error -- so the maintenance job is mandatory in prod.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _months_from(start: datetime, count: int) -> list[tuple[str, str, str]]:
    """Yield (suffix, start, end) tuples for ``count`` consecutive months."""
    out: list[tuple[str, str, str]] = []
    year, month = start.year, start.month
    for _ in range(count):
        nyear, nmonth = (year, month + 1) if month < 12 else (year + 1, 1)
        suffix = f"{year:04d}_{month:02d}"
        start_str = f"{year:04d}-{month:02d}-01"
        end_str = f"{nyear:04d}-{nmonth:02d}-01"
        out.append((suffix, start_str, end_str))
        year, month = nyear, nmonth
    return out


def upgrade() -> None:
    # ---- audit_events (partitioned by created_at) ----
    # Note: PostgreSQL requires the partition key to be in the primary key.
    # We use a composite PK (id, created_at) instead of just id.
    op.execute("""
        CREATE TABLE audit_events (
            id              UUID         NOT NULL DEFAULT uuid_generate_v4(),
            tenant_id       UUID         NOT NULL,
            actor_user_id   UUID,
            event_type      TEXT         NOT NULL,
            resource_type   TEXT         NOT NULL,
            resource_id     UUID,
            action          TEXT         NOT NULL,
            ip_address      INET,
            user_agent      TEXT,
            request_id      TEXT,
            before_state    JSONB,
            after_state     JSONB,
            metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    op.execute(
        "CREATE INDEX idx_audit_events_tenant_created "
        "ON audit_events(tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX idx_audit_events_resource "
        "ON audit_events(resource_type, resource_id)"
    )
    op.execute(
        "CREATE INDEX idx_audit_events_actor "
        "ON audit_events(actor_user_id, created_at) "
        "WHERE actor_user_id IS NOT NULL"
    )

    # ---- usage_records (partitioned by created_at) ----
    op.execute("""
        CREATE TABLE usage_records (
            id                UUID            NOT NULL DEFAULT uuid_generate_v4(),
            tenant_id         UUID            NOT NULL,
            user_id           UUID,
            query_session_id  UUID,
            usage_type        TEXT            NOT NULL
                CHECK (usage_type IN ('embedding', 'completion', 'rerank', 'storage', 'evaluation')),
            provider          TEXT,
            model_name        TEXT,
            input_tokens      INT             NOT NULL DEFAULT 0,
            output_tokens     INT             NOT NULL DEFAULT 0,
            unit_cost_usd     NUMERIC(12, 8),
            total_cost_usd    NUMERIC(12, 6),
            created_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    op.execute(
        "CREATE INDEX idx_usage_records_tenant_created "
        "ON usage_records(tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX idx_usage_records_session "
        "ON usage_records(query_session_id) WHERE query_session_id IS NOT NULL"
    )

    # Create initial 6 months of partitions starting from the current month.
    today = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    for suffix, start, end in _months_from(today, 6):
        op.execute(f"""
            CREATE TABLE audit_events_{suffix}
            PARTITION OF audit_events
            FOR VALUES FROM ('{start}') TO ('{end}')
        """)
        op.execute(f"""
            CREATE TABLE usage_records_{suffix}
            PARTITION OF usage_records
            FOR VALUES FROM ('{start}') TO ('{end}')
        """)

    # Default partition catches stragglers outside the planned ranges.
    # Operational rule: if a row lands in *_default, alert + create the missing
    # named partition + move the row.
    op.execute("CREATE TABLE audit_events_default PARTITION OF audit_events DEFAULT")
    op.execute("CREATE TABLE usage_records_default PARTITION OF usage_records DEFAULT")


def downgrade() -> None:
    # Dropping the parent cascades to all partitions.
    op.execute("DROP TABLE IF EXISTS usage_records CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE")
