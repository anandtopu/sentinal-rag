"""Tenant budget ORM model (ADR-0022)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantBudget(Base):
    __tablename__ = "tenant_budgets"
    __table_args__ = (
        CheckConstraint(
            "period_type IN ('day','week','month')",
            name="ck_tenant_budgets_period_type",
        ),
        CheckConstraint("limit_usd > 0", name="ck_tenant_budgets_limit_pos"),
        CheckConstraint(
            "soft_threshold_pct BETWEEN 0 AND 100",
            name="ck_tenant_budgets_soft_pct",
        ),
        CheckConstraint(
            "hard_threshold_pct BETWEEN 0 AND 200",
            name="ck_tenant_budgets_hard_pct",
        ),
        CheckConstraint(
            "current_period_end > current_period_start",
            name="ck_tenant_budgets_period_window",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_type: Mapped[str] = mapped_column(String, nullable=False)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    soft_threshold_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("80")
    )
    hard_threshold_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    downgrade_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    current_period_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
