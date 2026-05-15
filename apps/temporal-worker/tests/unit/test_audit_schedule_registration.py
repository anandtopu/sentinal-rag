"""Unit tests for audit reconciliation schedule registration helpers."""

from __future__ import annotations

from uuid import UUID

import pytest
from sentinelrag_worker.scripts.register_audit_schedule import (
    _build_schedule,
    _parse_tenant_ids,
)


@pytest.mark.unit
def test_parse_tenant_ids_rejects_empty_and_deduplicates() -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    assert _parse_tenant_ids(f" {tenant_id}, {tenant_id} ") == [tenant_id]

    with pytest.raises(ValueError, match="AUDIT_RECON_TENANT_IDS"):
        _parse_tenant_ids("")


@pytest.mark.unit
def test_build_schedule_validates_numeric_bounds() -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    with pytest.raises(ValueError, match="INTERVAL_HOURS"):
        _build_schedule(
            tenant_ids=[tenant_id],
            task_queue="audit",
            interval_hours=0,
            backfill=True,
            max_backfill=10,
        )

    with pytest.raises(ValueError, match="MAX_BACKFILL"):
        _build_schedule(
            tenant_ids=[tenant_id],
            task_queue="audit",
            interval_hours=24,
            backfill=True,
            max_backfill=-1,
        )


@pytest.mark.unit
def test_build_schedule_carries_audit_task_queue() -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    schedule = _build_schedule(
        tenant_ids=[tenant_id],
        task_queue="audit-prod",
        interval_hours=24,
        backfill=False,
        max_backfill=0,
    )

    assert schedule.action.task_queue == "audit-prod"
