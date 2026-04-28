"""Pure reconciliation logic — diffing the Postgres + S3 audit stores.

The Temporal activity in :mod:`sentinelrag_worker.activities.audit_reconciliation`
wires real DB queries and S3 listings as callables; this module orchestrates
them. Keeping the orchestration pure (no DB or boto imports) means unit tests
can exercise drift detection, backfill capping, and idempotency with in-memory
fakes — which matters because the only failure modes that produce silent data
loss live in this seam.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from sentinelrag_shared.audit.event import AuditEvent

PgEventLister = Callable[[UUID], Awaitable[list[UUID]]]
S3EventLister = Callable[[UUID], Awaitable[list[UUID]]]
PgEventFetcher = Callable[[UUID, UUID], Awaitable[AuditEvent | None]]
S3EventPutter = Callable[[AuditEvent], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class DriftCounts:
    """Set-difference output of ``diff_event_sets``."""

    missing_in_s3: list[UUID]  # in PG, not in S3 — backfill candidates
    missing_in_pg: list[UUID]  # in S3, not in PG — orphan archive entries
    in_both: int


@dataclass(slots=True, frozen=True)
class TenantReconcileResult:
    """Per-tenant outcome surfaced to the workflow result."""

    tenant_id: UUID
    pg_count: int
    s3_count: int
    missing_in_s3: int
    missing_in_pg: int
    backfilled: int


def diff_event_sets(
    pg_ids: Iterable[UUID], s3_ids: Iterable[UUID]
) -> DriftCounts:
    """Sorted set-difference. Sorted so workflow output is deterministic."""

    pg_set = set(pg_ids)
    s3_set = set(s3_ids)
    return DriftCounts(
        missing_in_s3=sorted(pg_set - s3_set),
        missing_in_pg=sorted(s3_set - pg_set),
        in_both=len(pg_set & s3_set),
    )


async def reconcile_one_tenant(
    *,
    tenant_id: UUID,
    list_pg_events: PgEventLister,
    list_s3_events: S3EventLister,
    fetch_pg_event: PgEventFetcher,
    put_to_s3: S3EventPutter,
    backfill_missing_in_s3: bool,
    max_backfill: int,
) -> TenantReconcileResult:
    """Reconcile one tenant's day-partition.

    Reads both stores, diffs them, and (if enabled) re-uploads up to
    ``max_backfill`` events that exist in Postgres but not in S3. Orphans in
    S3 (missing from PG) are reported but never deleted — Object Lock makes
    that physically impossible and the alarm is the right response anyway.

    Re-running the same window is safe: ``put_to_s3`` overwrites in place and
    Object Lock retention restarts at the new put. The pre-existing object's
    retention guarantee is unchanged because the same content lands at the
    same key.
    """

    pg_ids = await list_pg_events(tenant_id)
    s3_ids = await list_s3_events(tenant_id)
    drift = diff_event_sets(pg_ids, s3_ids)

    backfilled = 0
    if backfill_missing_in_s3 and drift.missing_in_s3 and max_backfill > 0:
        for event_id in drift.missing_in_s3[:max_backfill]:
            event = await fetch_pg_event(tenant_id, event_id)
            if event is None:
                # Race: row was deleted between list and fetch. The fact that
                # an audit row was deleted at all is a separate alarm — log it
                # at the activity layer, but don't fail the whole window.
                continue
            await put_to_s3(event)
            backfilled += 1

    return TenantReconcileResult(
        tenant_id=tenant_id,
        pg_count=len(pg_ids),
        s3_count=len(s3_ids),
        missing_in_s3=len(drift.missing_in_s3),
        missing_in_pg=len(drift.missing_in_pg),
        backfilled=backfilled,
    )
