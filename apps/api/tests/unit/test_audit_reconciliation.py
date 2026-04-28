"""Unit tests for the audit reconciliation pure logic (Phase 6.5).

We don't test the Temporal activity wrappers here — those just bind real DB +
S3 callables to the pure ``reconcile_one_tenant`` function below. The seam we
care about is the diff + backfill orchestration; integration tests against a
real Postgres + MinIO live in ``tests/integration/`` (deferred until the
docker-up session).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sentinelrag_shared.audit import (
    AuditEvent,
    diff_event_sets,
    reconcile_one_tenant,
)


def _event(tenant_id: UUID, **overrides: object) -> AuditEvent:
    base: dict[str, object] = {
        "tenant_id": tenant_id,
        "event_type": "query.executed",
        "action": "execute",
    }
    base.update(overrides)
    return AuditEvent(**base)  # type: ignore[arg-type]


# ---- diff_event_sets --------------------------------------------------------


@pytest.mark.unit
class TestDiffEventSets:
    def test_full_overlap_yields_no_drift(self) -> None:
        ids = [uuid4() for _ in range(3)]
        d = diff_event_sets(ids, ids)
        assert d.missing_in_s3 == []
        assert d.missing_in_pg == []
        assert d.in_both == 3

    def test_pg_only_events_are_missing_in_s3(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        d = diff_event_sets([a, b, c], [a])
        assert set(d.missing_in_s3) == {b, c}
        assert d.missing_in_pg == []
        assert d.in_both == 1

    def test_s3_only_events_are_missing_in_pg(self) -> None:
        a, b = uuid4(), uuid4()
        d = diff_event_sets([a], [a, b])
        assert d.missing_in_s3 == []
        assert d.missing_in_pg == [b]
        assert d.in_both == 1

    def test_output_is_sorted_for_deterministic_workflow_history(self) -> None:
        # uuid4() ordering is essentially random; sort by stringified UUID
        # to verify the diff helper sorts identically.
        ids = sorted([uuid4() for _ in range(5)])
        # PG sees them in reverse, S3 sees only the last one.
        d = diff_event_sets(list(reversed(ids)), [ids[-1]])
        assert d.missing_in_s3 == ids[:-1]

    def test_empty_inputs(self) -> None:
        d = diff_event_sets([], [])
        assert d.missing_in_s3 == []
        assert d.missing_in_pg == []
        assert d.in_both == 0


# ---- reconcile_one_tenant ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestReconcileOneTenant:
    async def _run(
        self,
        *,
        pg_events: list[AuditEvent],
        s3_keys: list[UUID],
        backfill: bool = True,
        max_backfill: int = 100,
    ) -> tuple[object, list[UUID]]:
        tenant_id = pg_events[0].tenant_id if pg_events else uuid4()
        by_id = {e.id: e for e in pg_events}
        s3_state: set[UUID] = set(s3_keys)
        put_log: list[UUID] = []

        async def list_pg(_t: UUID) -> list[UUID]:
            return list(by_id.keys())

        async def list_s3(_t: UUID) -> list[UUID]:
            return list(s3_state)

        async def fetch(_t: UUID, eid: UUID) -> AuditEvent | None:
            return by_id.get(eid)

        async def put(event: AuditEvent) -> None:
            s3_state.add(event.id)
            put_log.append(event.id)

        result = await reconcile_one_tenant(
            tenant_id=tenant_id,
            list_pg_events=list_pg,
            list_s3_events=list_s3,
            fetch_pg_event=fetch,
            put_to_s3=put,
            backfill_missing_in_s3=backfill,
            max_backfill=max_backfill,
        )
        return result, put_log

    async def test_no_drift_no_backfill(self) -> None:
        tenant = uuid4()
        events = [_event(tenant) for _ in range(3)]
        result, put_log = await self._run(
            pg_events=events, s3_keys=[e.id for e in events]
        )
        assert result.pg_count == 3
        assert result.s3_count == 3
        assert result.missing_in_s3 == 0
        assert result.missing_in_pg == 0
        assert result.backfilled == 0
        assert put_log == []

    async def test_backfills_pg_events_missing_from_s3(self) -> None:
        tenant = uuid4()
        events = [_event(tenant) for _ in range(4)]
        # Only 2 of the 4 are in S3.
        result, put_log = await self._run(
            pg_events=events, s3_keys=[events[0].id, events[1].id]
        )
        assert result.missing_in_s3 == 2
        assert result.backfilled == 2
        assert set(put_log) == {events[2].id, events[3].id}

    async def test_max_backfill_caps_repair_count(self) -> None:
        tenant = uuid4()
        events = [_event(tenant) for _ in range(10)]
        result, put_log = await self._run(
            pg_events=events, s3_keys=[], max_backfill=3
        )
        assert result.missing_in_s3 == 10
        assert result.backfilled == 3
        assert len(put_log) == 3

    async def test_backfill_disabled_reports_drift_but_does_not_repair(self) -> None:
        tenant = uuid4()
        events = [_event(tenant) for _ in range(2)]
        result, put_log = await self._run(
            pg_events=events, s3_keys=[], backfill=False
        )
        assert result.missing_in_s3 == 2
        assert result.backfilled == 0
        assert put_log == []

    async def test_orphan_s3_events_are_reported_not_deleted(self) -> None:
        tenant = uuid4()
        in_pg = [_event(tenant)]
        orphan = uuid4()
        result, put_log = await self._run(
            pg_events=in_pg, s3_keys=[in_pg[0].id, orphan]
        )
        # Orphan is reported, never touched — Object Lock makes deletion
        # impossible and the alarm is the right response.
        assert result.missing_in_pg == 1
        assert result.missing_in_s3 == 0
        assert put_log == []

    async def test_idempotent_rerun_yields_same_result(self) -> None:
        tenant = uuid4()
        events = [_event(tenant) for _ in range(3)]
        # First run repairs everything.
        first, first_log = await self._run(
            pg_events=events, s3_keys=[events[0].id]
        )
        assert first.backfilled == 2
        assert len(first_log) == 2

        # Second run with the now-repaired state — no drift, no puts.
        # Simulate "after repair" by including all event ids in s3_keys.
        second, second_log = await self._run(
            pg_events=events, s3_keys=[e.id for e in events]
        )
        assert second.missing_in_s3 == 0
        assert second.backfilled == 0
        assert second_log == []

    async def test_race_deleted_pg_row_is_skipped_not_failed(self) -> None:
        # Simulate the case where list_pg returns an id but fetch returns None
        # (row deleted between list and fetch). The reconciler must not raise.
        tenant = uuid4()
        present = _event(tenant)

        async def list_pg(_t: UUID) -> list[UUID]:
            ghost = UUID(int=present.id.int ^ 1)  # different but valid UUID
            return [present.id, ghost]

        async def list_s3(_t: UUID) -> list[UUID]:
            return []

        async def fetch(_t: UUID, eid: UUID) -> AuditEvent | None:
            return present if eid == present.id else None

        put_log: list[UUID] = []

        async def put(event: AuditEvent) -> None:
            put_log.append(event.id)

        result = await reconcile_one_tenant(
            tenant_id=tenant,
            list_pg_events=list_pg,
            list_s3_events=list_s3,
            fetch_pg_event=fetch,
            put_to_s3=put,
            backfill_missing_in_s3=True,
            max_backfill=100,
        )
        assert result.missing_in_s3 == 2
        assert result.backfilled == 1
        assert put_log == [present.id]


# ---- AuditEvent key helpers -------------------------------------------------


@pytest.mark.unit
class TestAuditEventKeyHelpers:
    def test_event_id_from_key_roundtrip(self) -> None:
        event = _event(uuid4())
        assert AuditEvent.event_id_from_key(event.s3_key()) == event.id

    def test_event_id_from_key_rejects_unexpected_suffix(self) -> None:
        with pytest.raises(ValueError, match="unexpected audit s3 key shape"):
            AuditEvent.event_id_from_key("tenant_id=x/year=2026/foo.txt")

    def test_day_prefix_matches_s3_key_for_same_day(self) -> None:
        tenant = uuid4()
        when = datetime(2026, 4, 28, 14, 30, tzinfo=UTC)
        event = _event(tenant, created_at=when)
        prefix = AuditEvent.day_prefix(tenant, when)
        assert event.s3_key().startswith(prefix)

    def test_day_prefix_excludes_other_days(self) -> None:
        tenant = uuid4()
        prefix_day1 = AuditEvent.day_prefix(
            tenant, datetime(2026, 4, 28, tzinfo=UTC)
        )
        event_day2 = _event(
            tenant, created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
        )
        assert not event_day2.s3_key().startswith(prefix_day1)
