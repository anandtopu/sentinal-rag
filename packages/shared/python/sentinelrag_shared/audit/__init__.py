"""Audit dual-write (ADR-0016) — Postgres + S3 Object Lock."""

from sentinelrag_shared.audit.event import AuditEvent
from sentinelrag_shared.audit.reconciliation import (
    DriftCounts,
    TenantReconcileResult,
    diff_event_sets,
    reconcile_one_tenant,
)
from sentinelrag_shared.audit.service import (
    AuditService,
    DualWriteAuditService,
    InMemoryAuditSink,
)
from sentinelrag_shared.audit.sinks import (
    AuditSink,
    AuditSinkError,
    ObjectStorageAuditSink,
    PostgresAuditSink,
)

__all__ = [
    "AuditEvent",
    "AuditService",
    "AuditSink",
    "AuditSinkError",
    "DriftCounts",
    "DualWriteAuditService",
    "InMemoryAuditSink",
    "ObjectStorageAuditSink",
    "PostgresAuditSink",
    "TenantReconcileResult",
    "diff_event_sets",
    "reconcile_one_tenant",
]
