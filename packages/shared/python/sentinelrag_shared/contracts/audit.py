"""Audit reconciliation workflow contracts."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from sentinelrag_shared.contracts.base import Contract


class AuditReconciliationInput(Contract):
    """Daily diff job input — one workflow run per day, fan-out by tenant.

    ``day`` is interpreted as a UTC calendar date; the workflow scans the
    ``[day 00:00 UTC, day+1 00:00 UTC)`` window in both Postgres and the
    S3 archive. When ``day`` is ``None`` (the recurring-Schedule shape) the
    workflow derives "yesterday UTC" from ``workflow.now()`` so each fire
    of a fixed-args Schedule reconciles the previous calendar day.
    """

    day: date | None = None
    tenant_ids: list[UUID] = Field(..., min_length=1)
    backfill_missing_in_s3: bool = True
    max_backfill_per_tenant: int = Field(default=500, ge=0)


class TenantDriftReport(Contract):
    tenant_id: UUID
    pg_count: int = Field(..., ge=0)
    s3_count: int = Field(..., ge=0)
    missing_in_s3: int = Field(..., ge=0)
    missing_in_pg: int = Field(..., ge=0)
    backfilled: int = Field(..., ge=0)


class AuditReconciliationResult(Contract):
    day: date
    reports: list[TenantDriftReport]

    @property
    def total_drift(self) -> int:
        return sum(r.missing_in_s3 + r.missing_in_pg for r in self.reports)
