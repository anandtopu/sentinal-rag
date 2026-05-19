"""Unit tests for the audit dual-write topology (ADR-0016)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sentinelrag_shared.audit import (
    AuditEvent,
    DualWriteAuditService,
    InMemoryAuditSink,
)
from sentinelrag_shared.audit import service as audit_service_module
from sentinelrag_shared.audit.sinks import AuditSinkError


def _event(**overrides: object) -> AuditEvent:
    base: dict[str, object] = {
        "tenant_id": uuid4(),
        "event_type": "query.executed",
        "action": "execute",
    }
    base.update(overrides)
    return AuditEvent(**base)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
class TestDualWriteAuditService:
    async def test_writes_to_primary_and_each_secondary(self) -> None:
        primary = InMemoryAuditSink()
        s1 = InMemoryAuditSink()
        s2 = InMemoryAuditSink()
        svc = DualWriteAuditService(primary=primary, secondaries=(s1, s2))

        event = _event()
        await svc.record(event)
        await svc.drain()

        assert [e.id for e in primary.records] == [event.id]
        assert [e.id for e in s1.records] == [event.id]
        assert [e.id for e in s2.records] == [event.id]

    async def test_secondary_failure_does_not_block_primary(self) -> None:
        primary = InMemoryAuditSink()
        flaky = InMemoryAuditSink()
        flaky.fail_next()
        svc = DualWriteAuditService(primary=primary, secondaries=(flaky,))

        event = _event()
        await svc.record(event)
        await svc.drain()

        # Primary still got it; secondary's failure was swallowed.
        assert [e.id for e in primary.records] == [event.id]
        assert flaky.records == []

    async def test_primary_failure_propagates(self) -> None:
        primary = InMemoryAuditSink()
        primary.fail_next()
        secondary = InMemoryAuditSink()
        svc = DualWriteAuditService(primary=primary, secondaries=(secondary,))

        with pytest.raises(AuditSinkError):
            await svc.record(_event())
        # Secondary must NOT see the event when the primary write failed.
        assert secondary.records == []

    async def test_secondary_unexpected_exception_is_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A secondary raising something other than AuditSinkError must not leak.

        Defensive R1.S4 widening: a misconfigured boto3 client raises
        ``ClientError`` not wrapped by ``AuditSinkError`` — the dual-write
        service swallows it and increments the meter.
        """

        class _BoomSink:
            async def write(self, event: AuditEvent) -> None:
                _ = event
                raise RuntimeError("boto3 ClientError surrogate")

        # Capture meter calls without depending on OTel SDK config.
        calls: list[str] = []
        monkeypatch.setattr(
            audit_service_module,
            "record_audit_secondary_failure",
            lambda *, sink: calls.append(sink),
        )

        primary = InMemoryAuditSink()
        svc = DualWriteAuditService(primary=primary, secondaries=(_BoomSink(),))

        await svc.record(_event())  # must NOT raise
        await svc.drain()

        assert len(primary.records) == 1
        assert calls == ["_BoomSink"]


@pytest.mark.unit
def test_event_s3_key_is_partitioned() -> None:
    event = _event()
    key = event.s3_key()
    parts = key.split("/")
    # tenant=, year=, month=, day=, hour=, <event_id>.json.gz
    assert parts[0].startswith("tenant_id=")
    assert parts[1].startswith("year=")
    assert parts[2].startswith("month=")
    assert parts[3].startswith("day=")
    assert parts[4].startswith("hour=")
    assert parts[5].endswith(".json.gz")
    assert str(event.id) in parts[5]


@pytest.mark.unit
def test_event_serializes_to_json() -> None:
    event = _event(metadata={"foo": "bar"})
    blob = event.model_dump_json()
    assert "query.executed" in blob
    assert '"foo":"bar"' in blob
