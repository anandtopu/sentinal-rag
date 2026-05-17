"""AuditService — orchestrates the dual-write topology (ADR-0016).

The service exposes a single ``record(event)`` call that:

1. Writes synchronously to the *primary* sink (Postgres) — failure
   propagates because the request transaction must roll back if the
   audit row didn't land.
2. Writes asynchronously to each *secondary* sink (S3 Object Lock).
   Failures are caught + logged but do NOT block the caller; the daily
   reconciliation job (Phase 6, deferred) backfills any gaps.

The async secondary write is fire-and-forget at the application layer.
Production deployments swap the in-process ``asyncio.create_task`` path
for a Redis Streams / Temporal signal queue (see ADR-0016 §"Write
coordination"); we keep the in-process variant for v1 to avoid dragging
Redis Streams into Phase 6's blast radius.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from typing import Protocol

from sentinelrag_shared.audit.event import AuditEvent
from sentinelrag_shared.audit.sinks import AuditSink, AuditSinkError
from sentinelrag_shared.telemetry import record_audit_secondary_failure

logger = logging.getLogger(__name__)


class AuditService(Protocol):
    async def record(self, event: AuditEvent) -> None: ...


class DualWriteAuditService:
    """Primary sink synchronous; secondary sinks fire-and-forget."""

    def __init__(
        self,
        *,
        primary: AuditSink,
        secondaries: Iterable[AuditSink] = (),
    ) -> None:
        self._primary = primary
        self._secondaries = tuple(secondaries)
        # Track in-flight tasks so tests / shutdown hooks can await drain.
        self._inflight: set[asyncio.Task[None]] = set()

    async def record(self, event: AuditEvent) -> None:
        # 1. Synchronous primary — error must propagate.
        await self._primary.write(event)

        # 2. Asynchronous secondaries — best-effort.
        for sink in self._secondaries:
            task = asyncio.create_task(self._safe_write(sink, event))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _safe_write(self, sink: AuditSink, event: AuditEvent) -> None:
        """Best-effort secondary write — never propagate to the caller.

        Catches ``AuditSinkError`` (the wrapped failure mode) AND broader
        ``Exception`` defensively — a misconfigured boto3 client can raise
        ``ClientError`` not wrapped by ``AuditSinkError``, and leaking those
        as an asyncio "Task exception was never retrieved" surprises
        operators. The daily reconciliation Schedule (Phase 6.5) backfills
        any missed rows; this counter is the early-warning signal.
        """
        sink_name = type(sink).__name__
        try:
            await sink.write(event)
        except Exception as exc:
            logger.warning(
                "audit secondary sink failed",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "sink": sink_name,
                    "error": str(exc),
                },
            )
            # Telemetry may not be configured in unit tests; suppress so a
            # missing OTel SDK never masks the original failure signal.
            with contextlib.suppress(Exception):
                record_audit_secondary_failure(sink=sink_name)

    async def drain(self) -> None:
        """Wait for in-flight async writes to settle.

        Useful for tests + a graceful-shutdown hook in app lifecycle.
        """
        if not self._inflight:
            return
        await asyncio.gather(*self._inflight, return_exceptions=True)


class InMemoryAuditSink:
    """Test sink — exposes a ``records`` list for assertions."""

    def __init__(self) -> None:
        self.records: list[AuditEvent] = []
        self._fail = False

    def fail_next(self) -> None:
        self._fail = True

    async def write(self, event: AuditEvent) -> None:
        if self._fail:
            self._fail = False
            raise AuditSinkError("in-memory sink: forced failure")
        self.records.append(event)
