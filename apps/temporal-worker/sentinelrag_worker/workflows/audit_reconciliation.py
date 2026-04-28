"""AuditReconciliationWorkflow — daily diff between Postgres and S3 archive.

Closes the ADR-0016 dual-write loop: the in-process secondary is
fire-and-forget, so a transient S3 failure can leave a Postgres row without
its archive twin. This workflow runs daily (Temporal Schedule), enumerates
both stores for each configured tenant, re-uploads any missing-in-S3 events
(capped per run), and emits drift metrics + a structured log line so the
on-call alarm has something to fire on.

The workflow itself is intentionally trivial — all I/O is in activities so
replay determinism is preserved. We do an explicit ``sorted(...)`` over
tenant_ids before iterating so workflow history is deterministic regardless
of the input ordering supplied by the caller.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sentinelrag_shared.contracts import (
        AuditReconciliationInput,
        AuditReconciliationResult,
        TenantDriftReport,
    )

    from sentinelrag_worker.activities import audit_reconciliation as activities


_TENANT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=5),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)


@workflow.defn(name="AuditReconciliationWorkflow")
class AuditReconciliationWorkflow:
    @workflow.run
    async def run(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        payload = AuditReconciliationInput.model_validate(raw_payload)

        # Recurring Schedule shape: day omitted → reconcile yesterday-UTC,
        # derived from workflow.now() so replay stays deterministic.
        day = payload.day or (
            workflow.now().astimezone(UTC).date() - timedelta(days=1)
        )

        # Sorted iteration so workflow history is deterministic across
        # re-queues regardless of caller-side ordering.
        tenant_ids = sorted(str(t) for t in payload.tenant_ids)
        day_iso = day.isoformat()

        reports: list[dict[str, Any]] = []
        for tenant_id_s in tenant_ids:
            report = await workflow.execute_activity(
                activities.reconcile_tenant_day,
                args=[
                    tenant_id_s,
                    day_iso,
                    payload.backfill_missing_in_s3,
                    payload.max_backfill_per_tenant,
                ],
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=_TENANT_RETRY,
            )
            reports.append(report)

        await workflow.execute_activity(
            activities.emit_audit_drift_metrics,
            args=[reports],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        result = AuditReconciliationResult(
            day=day,
            reports=[TenantDriftReport.model_validate(r) for r in reports],
        )
        return result.model_dump(mode="json")
