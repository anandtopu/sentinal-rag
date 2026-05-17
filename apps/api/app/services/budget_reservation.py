"""BudgetReservationService — Redis-backed pre-spend reservations (R3.S5).

Why: today the budget gate compares ``current_spend + estimate`` against
caps using only ``usage_records`` rows that have *already been written*.
Under load with provider timeouts, in-flight requests can each pass the
gate before any of them book a usage row, allowing a tenant to burst
past the hard cap. R3.S5 closes this by reserving the estimated spend
in Redis the moment the gate runs; the reservation auto-expires when
the call's wall-clock budget is up, and is released explicitly on
success or timeout. The gate sums reservations into projected spend so
the second concurrent request sees the first's pending charge.

Storage shape:

- One key per reservation: ``budget:resv:{tenant_id}:{request_id}`` with
  the amount as a stringified Decimal.
- TTL = generation timeout + cushion. Auto-cleanup if the orchestrator
  crashes before ``release``.

The Redis client may be ``None`` — methods short-circuit to zero
reservations + no-op release. That keeps tests + local dev cheap; the
production deploy gets the real protection.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis


# Conservative cushion above ``generation_timeout_seconds``. If the
# orchestrator times out + the release fails, the reservation still
# decays within a couple of minutes rather than starving the tenant
# for hours.
_RESERVATION_CUSHION_SECONDS: Final[int] = 30

_log = structlog.get_logger(__name__)


class BudgetReservationService:
    def __init__(self, client: Redis | None) -> None:
        self._client = client

    @staticmethod
    def reservation_key(*, tenant_id: UUID, request_id: UUID) -> str:
        return f"budget:resv:{tenant_id}:{request_id}"

    @staticmethod
    def tenant_prefix(*, tenant_id: UUID) -> str:
        return f"budget:resv:{tenant_id}:*"

    async def reserve(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        amount_usd: Decimal,
        ttl_seconds: float,
    ) -> bool:
        """Stash an in-flight charge for ``ttl + cushion`` seconds.

        Returns False on Redis failure or no-client — callers should
        proceed without reservation rather than block the request, but
        log so an operator can wire Redis when they care about the
        gate.
        """
        if self._client is None or amount_usd <= 0:
            return False
        ttl = max(1, int(ttl_seconds) + _RESERVATION_CUSHION_SECONDS)
        try:
            await self._client.set(
                self.reservation_key(tenant_id=tenant_id, request_id=request_id),
                str(amount_usd),
                ex=ttl,
            )
            return True
        except Exception as exc:
            _log.warning(
                "budget_reservation.reserve_failed",
                tenant_id=str(tenant_id),
                request_id=str(request_id),
                exception=str(exc)[:200],
            )
            return False

    async def release(
        self, *, tenant_id: UUID, request_id: UUID
    ) -> None:
        """Drop a reservation when the request completes (any outcome).

        Idempotent: deleting an absent key is fine. We don't fail loudly
        — if the request is unwinding from a failure, an extra warning
        in the log helps nobody.
        """
        if self._client is None:
            return
        try:
            await self._client.delete(
                self.reservation_key(tenant_id=tenant_id, request_id=request_id)
            )
        except Exception as exc:
            _log.warning(
                "budget_reservation.release_failed",
                tenant_id=str(tenant_id),
                request_id=str(request_id),
                exception=str(exc)[:200],
            )

    async def total_reserved(self, *, tenant_id: UUID) -> Decimal:
        """Sum of live reservations for the tenant.

        Used by :class:`CostService.check_budget` to add in-flight spend
        to ``current_spend`` before comparing against caps.

        SCAN over a per-tenant prefix is bounded by concurrent in-flight
        queries per tenant — typically a small number.
        """
        if self._client is None:
            return Decimal("0")
        total = Decimal("0")
        try:
            cursor = 0
            pattern = self.tenant_prefix(tenant_id=tenant_id)
            while True:
                cursor, keys = await self._client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    values = await self._client.mget(*keys)
                    for v in values:
                        if v is None:
                            continue
                        try:
                            total += Decimal(v)
                        except (ArithmeticError, ValueError):
                            continue
                if cursor == 0:
                    break
        except Exception as exc:
            _log.warning(
                "budget_reservation.total_reserved_failed",
                tenant_id=str(tenant_id),
                exception=str(exc)[:200],
            )
            return Decimal("0")
        return total
