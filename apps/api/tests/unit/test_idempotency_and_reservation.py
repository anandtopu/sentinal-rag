"""Unit coverage for R3.S2 (Idempotency) + R3.S5 (Budget reservations).

The services are exercised against a small in-memory fake of the
``redis.asyncio.Redis`` surface they actually use (``set``, ``get``,
``delete``, ``scan``, ``mget``, ``ping``). The fake is intentionally
minimal — these tests are not a Redis conformance suite; they verify
the service-side contracts.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from app.services.budget_reservation import BudgetReservationService
from app.services.idempotency import IdempotencyService


class _FakeRedis:
    """Minimal subset of redis.asyncio.Redis used by the two services.

    Stores (value, expires_at_epoch_s) tuples; reads check expiry so
    TTL behavior is testable without real time.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self) -> None:
        now = self._now()
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            del self._store[k]

    async def ping(self) -> bool:
        return True

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        self._prune()
        if nx and key in self._store:
            return False
        expiry = self._now() + (ex if ex is not None else 3600 * 24)
        self._store[key] = (value, expiry)
        return True

    async def get(self, key: str) -> str | None:
        self._prune()
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def delete(self, *keys: str) -> int:
        self._prune()
        n = 0
        for k in keys:
            if self._store.pop(k, None) is not None:
                n += 1
        return n

    async def scan(
        self, *, cursor: int = 0, match: str | None = None, count: int = 100
    ) -> tuple[int, list[str]]:
        self._prune()
        del cursor, count
        if match is None:
            keys = list(self._store.keys())
        else:
            import fnmatch  # noqa: PLC0415

            keys = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return 0, keys  # one-shot SCAN

    async def mget(self, *keys: str) -> list[str | None]:
        self._prune()
        return [self._store.get(k, (None,))[0] for k in keys]


# ---------- IdempotencyService ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_claim_returns_true_for_first_caller() -> None:
    svc = IdempotencyService(_FakeRedis())
    key = "idempotency:t1:k1:body"
    assert await svc.try_claim(key) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_claim_returns_false_for_second_caller() -> None:
    svc = IdempotencyService(_FakeRedis())
    key = "idempotency:t1:k1:body"
    assert await svc.try_claim(key) is True
    assert await svc.try_claim(key) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_store_replaces_pending_with_result() -> None:
    svc = IdempotencyService(_FakeRedis())
    key = "idempotency:t1:k1:body"
    await svc.try_claim(key)
    await svc.store_result(key, json.dumps({"answer": "hi"}))
    cached = await svc.get_cached(key)
    assert cached == {"answer": "hi"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_get_cached_returns_pending_marker() -> None:
    svc = IdempotencyService(_FakeRedis())
    key = "idempotency:t1:k1:body"
    await svc.try_claim(key)
    cached = await svc.get_cached(key)
    assert cached == {"__pending__": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_release_only_clears_pending() -> None:
    """A release after store_result must NOT clobber the stored result."""
    svc = IdempotencyService(_FakeRedis())
    key = "idempotency:t1:k1:body"
    await svc.try_claim(key)
    await svc.store_result(key, json.dumps({"answer": "hi"}))
    await svc.release_claim(key)
    cached = await svc.get_cached(key)
    assert cached == {"answer": "hi"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_no_redis_disables_caching() -> None:
    """With Redis unavailable, every caller becomes a leader."""
    svc = IdempotencyService(None)
    key = "idempotency:t1:k1:body"
    assert await svc.try_claim(key) is True
    assert await svc.get_cached(key) is None
    await svc.store_result(key, "anything")  # no-op
    assert await svc.get_cached(key) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_wait_returns_result_when_leader_stores() -> None:
    fake = _FakeRedis()
    svc = IdempotencyService(fake)
    key = "idempotency:t1:k1:body"
    await svc.try_claim(key)

    async def leader() -> None:
        await asyncio.sleep(0.01)
        await svc.store_result(key, json.dumps({"answer": "hi"}))

    leader_task = asyncio.create_task(leader())
    cached = await svc.wait_for_result(key)
    await leader_task
    assert cached == {"answer": "hi"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_wait_returns_none_when_leader_releases() -> None:
    fake = _FakeRedis()
    svc = IdempotencyService(fake)
    key = "idempotency:t1:k1:body"
    await svc.try_claim(key)

    async def failed_leader() -> None:
        await asyncio.sleep(0.01)
        await svc.release_claim(key)

    leader_task = asyncio.create_task(failed_leader())
    cached = await svc.wait_for_result(key)
    await leader_task
    assert cached is None


@pytest.mark.unit
def test_idempotency_body_hash_is_stable() -> None:
    h1 = IdempotencyService.body_hash(b'{"query":"hi"}')
    h2 = IdempotencyService.body_hash(b'{"query":"hi"}')
    h3 = IdempotencyService.body_hash(b'{"query":"different"}')
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 32  # truncated sha256


@pytest.mark.unit
def test_idempotency_cache_key_includes_tenant() -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    k_a = IdempotencyService.cache_key(tenant_id=tenant_a, idempotency_key="k1", body_hash="b1")
    k_b = IdempotencyService.cache_key(tenant_id=tenant_b, idempotency_key="k1", body_hash="b1")
    assert k_a != k_b
    assert str(tenant_a) in k_a
    assert str(tenant_b) in k_b


# ---------- BudgetReservationService ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reservation_round_trip() -> None:
    fake = _FakeRedis()
    svc = BudgetReservationService(fake)
    tenant = uuid4()
    req = uuid4()
    await svc.reserve(tenant_id=tenant, request_id=req, amount_usd=Decimal("0.02"), ttl_seconds=60)
    total = await svc.total_reserved(tenant_id=tenant)
    assert total == Decimal("0.02")
    await svc.release(tenant_id=tenant, request_id=req)
    assert await svc.total_reserved(tenant_id=tenant) == Decimal("0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reservation_total_sums_multiple_inflight() -> None:
    fake = _FakeRedis()
    svc = BudgetReservationService(fake)
    tenant = uuid4()
    await svc.reserve(
        tenant_id=tenant,
        request_id=uuid4(),
        amount_usd=Decimal("0.01"),
        ttl_seconds=60,
    )
    await svc.reserve(
        tenant_id=tenant,
        request_id=uuid4(),
        amount_usd=Decimal("0.05"),
        ttl_seconds=60,
    )
    total = await svc.total_reserved(tenant_id=tenant)
    assert total == Decimal("0.06")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reservation_zero_amount_is_not_reserved() -> None:
    """Negative or zero amounts must not pollute the per-tenant prefix."""
    fake = _FakeRedis()
    svc = BudgetReservationService(fake)
    tenant = uuid4()
    ok = await svc.reserve(
        tenant_id=tenant,
        request_id=uuid4(),
        amount_usd=Decimal("0"),
        ttl_seconds=60,
    )
    assert ok is False
    assert await svc.total_reserved(tenant_id=tenant) == Decimal("0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reservation_total_isolates_by_tenant() -> None:
    fake = _FakeRedis()
    svc = BudgetReservationService(fake)
    tenant_a = uuid4()
    tenant_b = uuid4()
    await svc.reserve(
        tenant_id=tenant_a,
        request_id=uuid4(),
        amount_usd=Decimal("1.0"),
        ttl_seconds=60,
    )
    await svc.reserve(
        tenant_id=tenant_b,
        request_id=uuid4(),
        amount_usd=Decimal("2.0"),
        ttl_seconds=60,
    )
    assert await svc.total_reserved(tenant_id=tenant_a) == Decimal("1.0")
    assert await svc.total_reserved(tenant_id=tenant_b) == Decimal("2.0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reservation_no_redis_returns_zero() -> None:
    svc = BudgetReservationService(None)
    assert await svc.total_reserved(tenant_id=uuid4()) == Decimal("0")
    # Reserve should silently no-op rather than raise.
    assert (
        await svc.reserve(
            tenant_id=uuid4(),
            request_id=uuid4(),
            amount_usd=Decimal("1.0"),
            ttl_seconds=60,
        )
        is False
    )
    await svc.release(tenant_id=uuid4(), request_id=uuid4())  # must not raise
