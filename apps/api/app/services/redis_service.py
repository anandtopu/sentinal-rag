"""Thin async Redis client wrapper.

The Redis client is constructed once per process by ``app/lifecycle.py``
and lives on ``app.state.redis``. Routes/services pull it via a
FastAPI dependency. We do NOT pool per request — ``redis.asyncio.Redis``
already manages its own connection pool internally.

A ``None`` Redis is treated as "feature unavailable" by the consumers
(Idempotency, BudgetReservation). That keeps local dev usable when
Redis isn't up — degraded behavior, never crashing.
"""

from __future__ import annotations

from redis.asyncio import Redis


def build_redis_client(*, redis_url: str) -> Redis:
    """Construct an async Redis client.

    Decoding responses so callers don't have to bytes/str juggle in
    every codepath. The client's own pool defaults are fine.
    """
    return Redis.from_url(redis_url, decode_responses=True)


async def ping_or_none(client: Redis | None) -> bool:
    """Return True iff a non-None client successfully responds to PING.

    Used in the lifespan startup probe so we can log whether Redis is
    actually reachable rather than waiting for the first cache miss to
    surface a connection error.
    """
    if client is None:
        return False
    try:
        # redis.asyncio's ping returns Awaitable[bool] at runtime; the
        # stubs lie about it (declared as ``bool``) so we ignore the type
        # check here rather than letting a real await crash production.
        result = await client.ping()  # type: ignore[misc]
        return bool(result)
    except Exception:
        return False
