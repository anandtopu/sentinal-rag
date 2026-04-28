"""Audit reconciliation activities (Phase 6.5).

The pure orchestration lives in :func:`sentinelrag_shared.audit.reconciliation`;
this module wires the real Postgres + S3 callables it expects, plus an
emit_drift activity that pushes the result into the OTel meter and the
structured log.

The activity that does the work for one tenant is the one Temporal retries on
failure. It is idempotent: re-running it overwrites the same S3 keys, so a
mid-run crash that retried after partial backfill yields the same final state.
"""

from __future__ import annotations

import gzip
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sentinelrag_shared.audit import (
    AuditEvent,
    TenantReconcileResult,
    reconcile_one_tenant,
)
from sentinelrag_shared.logging import get_logger
from sentinelrag_shared.object_storage import ObjectStorage, build_object_storage
from sentinelrag_shared.telemetry.meters import record_audit_drift
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from temporalio import activity

log = get_logger(__name__)

# ---- DB engine / session ----------------------------------------------------
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory  # noqa: PLW0603
    if _session_factory is None:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinelrag",
        )
        _engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=5)
        _session_factory = async_sessionmaker(
            bind=_engine, expire_on_commit=False, autoflush=False
        )
    return _session_factory


@asynccontextmanager
async def _session_for_tenant(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield session


# ---- Audit-archive S3 client ------------------------------------------------
def _build_audit_storage() -> ObjectStorage:
    return build_object_storage(
        provider=os.environ.get("OBJECT_STORAGE_PROVIDER", "minio"),
        bucket=os.environ.get(
            "OBJECT_STORAGE_BUCKET_AUDIT", "sentinelrag-audit"
        ),
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        endpoint=os.environ.get("OBJECT_STORAGE_ENDPOINT"),
        access_key=os.environ.get("OBJECT_STORAGE_ACCESS_KEY"),
        secret_key=os.environ.get("OBJECT_STORAGE_SECRET_KEY"),
        verify_ssl=False,
    )


def _day_window(day_iso: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(day_iso)
    start = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


# ---- Activity: reconcile one tenant for one day ----------------------------
@activity.defn(name="reconcile_tenant_day")
async def reconcile_tenant_day(
    tenant_id_s: str,
    day_iso: str,
    backfill: bool,
    max_backfill: int,
) -> dict[str, Any]:
    """Reconcile one tenant's day partition.

    Returns a JSON-serializable dict matching ``TenantDriftReport``. The
    workflow aggregates these and emits the drift metric in a separate
    activity so a slow metric backend can't stall the per-tenant loop.
    """

    tenant_id = UUID(tenant_id_s)
    window_start, window_end = _day_window(day_iso)
    storage = _build_audit_storage()

    async def _list_pg(_t: UUID) -> list[UUID]:
        async with _session_for_tenant(tenant_id) as session:
            rows = await session.execute(
                text(
                    "SELECT id FROM audit_events "
                    "WHERE tenant_id = :tid "
                    "  AND created_at >= :start AND created_at < :end"
                ),
                {"tid": str(tenant_id), "start": window_start, "end": window_end},
            )
            return [UUID(str(row[0])) for row in rows]

    async def _list_s3(_t: UUID) -> list[UUID]:
        prefix = AuditEvent.day_prefix(tenant_id, window_start)
        ids: list[UUID] = []
        async for key in storage.list_keys(prefix):
            try:
                ids.append(AuditEvent.event_id_from_key(key))
            except ValueError:
                # Key shape doesn't match — log + skip rather than fail the
                # whole window. A foreign object in the bucket is a separate
                # alarm condition.
                log.warning("audit.reconcile.unexpected_key", key=key)
        return ids

    async def _fetch_pg(_t: UUID, event_id: UUID) -> AuditEvent | None:
        async with _session_for_tenant(tenant_id) as session:
            result = await session.execute(
                text(
                    "SELECT id, tenant_id, actor_user_id, event_type, "
                    "  resource_type, resource_id, action, ip_address, "
                    "  user_agent, request_id, before_state, after_state, "
                    "  metadata, created_at "
                    "FROM audit_events "
                    "WHERE tenant_id = :tid AND id = :eid"
                ),
                {"tid": str(tenant_id), "eid": str(event_id)},
            )
            row = result.first()
            if row is None:
                return None
            return AuditEvent(
                id=UUID(str(row[0])),
                tenant_id=UUID(str(row[1])),
                actor_user_id=UUID(str(row[2])) if row[2] else None,
                event_type=row[3],
                resource_type=row[4],
                resource_id=UUID(str(row[5])) if row[5] else None,
                action=row[6],
                ip_address=row[7],
                user_agent=row[8],
                request_id=row[9],
                before_state=row[10],
                after_state=row[11],
                metadata=row[12] or {},
                created_at=row[13],
            )

    async def _put_s3(event: AuditEvent) -> None:
        payload = event.model_dump_json().encode("utf-8")
        body = gzip.compress(payload)
        await storage.put(
            key=event.s3_key(),
            data=body,
            content_type="application/gzip",
            custom_metadata={
                "event-type": event.event_type,
                "tenant-id": str(event.tenant_id),
                "backfilled": "true",
            },
        )

    try:
        result: TenantReconcileResult = await reconcile_one_tenant(
            tenant_id=tenant_id,
            list_pg_events=_list_pg,
            list_s3_events=_list_s3,
            fetch_pg_event=_fetch_pg,
            put_to_s3=_put_s3,
            backfill_missing_in_s3=backfill,
            max_backfill=max_backfill,
        )
    finally:
        await storage.close()

    return {
        "tenant_id": str(result.tenant_id),
        "pg_count": result.pg_count,
        "s3_count": result.s3_count,
        "missing_in_s3": result.missing_in_s3,
        "missing_in_pg": result.missing_in_pg,
        "backfilled": result.backfilled,
    }


# ---- Activity: emit drift metrics for the run ------------------------------
@activity.defn(name="emit_audit_drift_metrics")
async def emit_audit_drift_metrics(reports: list[dict[str, Any]]) -> None:
    """Push aggregated drift counts to OTel + structured log.

    Run as one activity at the end so a slow metrics backend can't fan-out
    stall the per-tenant reconciliation. The structured log line carries
    ``tenant_id`` since the metric purposely doesn't (cardinality discipline).
    """

    total_missing_in_s3 = 0
    total_missing_in_pg = 0
    total_backfilled = 0

    for r in reports:
        unrecovered = r["missing_in_s3"] - r["backfilled"]
        record_audit_drift(side="missing_in_s3", count=unrecovered)
        record_audit_drift(side="missing_in_pg", count=r["missing_in_pg"])
        record_audit_drift(side="backfilled", count=r["backfilled"])

        total_missing_in_s3 += unrecovered
        total_missing_in_pg += r["missing_in_pg"]
        total_backfilled += r["backfilled"]

        if r["missing_in_s3"] or r["missing_in_pg"]:
            log.warning(
                "audit.reconcile.drift",
                tenant_id=r["tenant_id"],
                pg_count=r["pg_count"],
                s3_count=r["s3_count"],
                missing_in_s3=r["missing_in_s3"],
                missing_in_pg=r["missing_in_pg"],
                backfilled=r["backfilled"],
                unrecovered=unrecovered,
            )

    log.info(
        "audit.reconcile.summary",
        tenants=len(reports),
        unrecovered_missing_in_s3=total_missing_in_s3,
        missing_in_pg=total_missing_in_pg,
        backfilled=total_backfilled,
    )


ALL_ACTIVITIES = [reconcile_tenant_day, emit_audit_drift_metrics]
