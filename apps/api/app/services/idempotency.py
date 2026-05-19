"""IdempotencyService — POST /query Idempotency-Key cache (R3.S2).

Behavior (per the remediation plan):

- Caller sends an ``Idempotency-Key`` header on POST /query.
- Key is namespaced by ``tenant_id`` so two tenants reusing the same
  caller-supplied key never collide.
- We also hash the request body into the cache key so a client cannot
  retry the same key with a different payload and get the cached
  response of the old payload.
- First request claims the key with a ``"pending"`` marker (SETNX); on
  success the response JSON replaces the marker with a 24h TTL.
- A second request with the same key:
  - finds the stored response JSON → returns it immediately;
  - finds the ``"pending"`` marker → polls briefly (cap = pending TTL)
    waiting for the leader to finish, then returns the result; if the
    leader fails or the pending marker expires the follower starts
    over.

Redis being unavailable degrades the feature gracefully — the route
falls back to the no-cache path and logs a warning.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis


_PENDING_TTL_SECONDS: Final[int] = 90
_RESULT_TTL_SECONDS: Final[int] = 24 * 60 * 60  # 24h per ADR-0022 / plan
_POLL_INTERVAL_SECONDS: Final[float] = 0.25
_POLL_MAX_TICKS: Final[int] = 240  # 240 * 0.25s = 60s
_PENDING_VALUE: Final[str] = "__pending__"

_log = structlog.get_logger(__name__)


class IdempotencyConflictError(Exception):
    """A concurrent request is in flight and didn't complete in time."""


class IdempotencyService:
    """Stateless service; the actual state lives in Redis.

    Args:
        client: redis.asyncio.Redis. May be None — methods treat that as
            "feature disabled" and short-circuit to no-cache behavior.
    """

    def __init__(self, client: Redis | None) -> None:
        self._client = client

    @staticmethod
    def cache_key(
        *,
        tenant_id: UUID,
        idempotency_key: str,
        body_hash: str,
    ) -> str:
        return f"idempotency:{tenant_id}:{idempotency_key}:{body_hash}"

    @staticmethod
    def body_hash(body_bytes: bytes) -> str:
        return hashlib.sha256(body_bytes).hexdigest()[:32]

    async def try_claim(self, key: str) -> bool:
        """Atomically claim the key as 'leader'. Returns True if claimed."""
        if self._client is None:
            return True  # no redis → every caller is the leader
        try:
            claimed = await self._client.set(key, _PENDING_VALUE, nx=True, ex=_PENDING_TTL_SECONDS)
            return bool(claimed)
        except Exception as exc:
            _log.warning(
                "idempotency.claim_failed_degrading_to_no_cache",
                key=key,
                exception=str(exc)[:200],
            )
            return True

    async def store_result(self, key: str, result_json: str) -> None:
        """Persist the leader's result under the claimed key with 24h TTL."""
        if self._client is None:
            return
        try:
            await self._client.set(key, result_json, ex=_RESULT_TTL_SECONDS)
        except Exception as exc:
            _log.warning(
                "idempotency.store_failed_response_was_unique",
                key=key,
                exception=str(exc)[:200],
            )

    async def release_claim(self, key: str) -> None:
        """Free the pending marker so retries don't wait on a dead leader.

        Only deletes the key if it's still the pending sentinel — never
        clobbers a stored result that another contender already wrote.
        """
        if self._client is None:
            return
        try:
            current = await self._client.get(key)
            if current == _PENDING_VALUE:
                await self._client.delete(key)
        except Exception as exc:
            _log.warning(
                "idempotency.release_failed",
                key=key,
                exception=str(exc)[:200],
            )

    async def get_cached(self, key: str) -> dict[str, Any] | None:
        """Return the cached response dict, or None on miss.

        Returns None for a missing key, ``{"__pending__": True}`` if a
        leader is still running, and the decoded response dict otherwise.
        """
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            _log.warning(
                "idempotency.get_failed_degrading_to_no_cache",
                key=key,
                exception=str(exc)[:200],
            )
            return None
        if raw is None:
            return None
        if raw == _PENDING_VALUE:
            return {"__pending__": True}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            _log.warning("idempotency.cached_value_unparseable", key=key)
            return None

    async def wait_for_result(self, key: str) -> dict[str, Any] | None:
        """Poll the cache until a result lands, or give up.

        Returns the cached response dict on success, ``None`` on
        give-up. Used by followers when the leader is still running.
        """
        for _ in range(_POLL_MAX_TICKS):
            cached = await self.get_cached(key)
            if cached is None:
                # Leader bailed and freed the claim — let the follower
                # try again as a fresh leader.
                return None
            if "__pending__" not in cached:
                return cached
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        return None
