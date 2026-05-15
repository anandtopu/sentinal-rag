"""Register (or update) the daily audit-reconciliation Temporal Schedule.

Idempotent: re-running with the same ID upserts the spec + arg list. Run after
deploy, or whenever the active-tenant set changes:

    uv run --package sentinelrag-temporal-worker \\
        python -m sentinelrag_worker.scripts.register_audit_schedule

Tenant IDs come from ``AUDIT_RECON_TENANT_IDS`` (comma-separated UUIDs). The
workflow derives "yesterday UTC" itself per fire, so the static schedule args
remain valid forever.

For ad-hoc replay of a specific past day, do NOT use this script — start the
workflow directly with ``day=<iso date>`` set.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import UUID

from sentinelrag_shared.contracts import AuditReconciliationInput
from sentinelrag_shared.logging import configure_logging, get_logger
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

from sentinelrag_worker.settings import env_bool, env_int, load_worker_settings

SCHEDULE_ID = "audit-reconciliation-daily"


def _parse_tenant_ids(raw: str) -> list[UUID]:
    ids = list(dict.fromkeys(UUID(s.strip()) for s in raw.split(",") if s.strip()))
    if not ids:
        raise ValueError(
            "AUDIT_RECON_TENANT_IDS is empty; "
            "set it to a comma-separated list of tenant UUIDs"
        )
    return ids


def _build_schedule(
    *,
    tenant_ids: list[UUID],
    task_queue: str,
    interval_hours: int,
    backfill: bool,
    max_backfill: int,
) -> Schedule:
    if interval_hours < 1:
        raise ValueError("AUDIT_RECON_INTERVAL_HOURS must be >= 1.")
    if max_backfill < 0:
        raise ValueError("AUDIT_RECON_MAX_BACKFILL must be >= 0.")

    payload = AuditReconciliationInput(
        day=None,  # workflow derives yesterday-UTC each fire
        tenant_ids=tenant_ids,
        backfill_missing_in_s3=backfill,
        max_backfill_per_tenant=max_backfill,
    )
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "AuditReconciliationWorkflow",
            payload.model_dump(mode="json"),
            id=f"{SCHEDULE_ID}-run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(every=timedelta(hours=interval_hours))
            ],
        ),
    )


async def main() -> None:
    settings = load_worker_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.environment != "local",
        service_name="sentinelrag-audit-schedule-register",
    )
    log = get_logger(__name__)

    task_queue = settings.audit_task_queue
    interval_hours = env_int("AUDIT_RECON_INTERVAL_HOURS", default=24, minimum=1)
    backfill = env_bool("AUDIT_RECON_BACKFILL", default=True)
    max_backfill = env_int("AUDIT_RECON_MAX_BACKFILL", default=500, minimum=0)
    tenant_ids = _parse_tenant_ids(os.environ.get("AUDIT_RECON_TENANT_IDS", ""))

    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )
    schedule = _build_schedule(
        tenant_ids=tenant_ids,
        task_queue=task_queue,
        interval_hours=interval_hours,
        backfill=backfill,
        max_backfill=max_backfill,
    )

    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
        log.info(
            "audit.schedule.created",
            schedule_id=SCHEDULE_ID,
            tenants=len(tenant_ids),
            interval_hours=interval_hours,
        )
    except ScheduleAlreadyRunningError:
        # Idempotent re-register: replace the spec with the latest config.
        async def _update(_old: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=schedule)

        await client.get_schedule_handle(SCHEDULE_ID).update(_update)
        log.info(
            "audit.schedule.updated",
            schedule_id=SCHEDULE_ID,
            tenants=len(tenant_ids),
            interval_hours=interval_hours,
        )


if __name__ == "__main__":
    asyncio.run(main())
