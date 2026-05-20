"""Operational metrics summary service (ADR-0038).

Read-model over ``query_sessions``: turns a window choice into scalar rates +
latency percentiles + a gap-filled time series for the console's topbar chips
and dashboard sparkline. All shaping (window→interval mapping, rate math,
bucket gap-fill) lives here so it's unit-testable with a fake repository; the
raw SQL lives in ``QuerySessionRepository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.query_sessions import QuerySessionRepository
from app.schemas.metrics import LatencyPercentiles, MetricsBucket, MetricsSummary


@dataclass(frozen=True)
class _WindowConfig:
    lookback: timedelta
    grain_sql: str  # Postgres interval literal for date_bin
    grain: timedelta  # same span, for Python boundary generation


# Allow-listed windows. Each fixes its own bucket grain so the sparkline lands
# a sensible number of points (12 / 24 / 7).
WINDOW_CONFIG: dict[str, _WindowConfig] = {
    "1h": _WindowConfig(timedelta(hours=1), "5 minutes", timedelta(minutes=5)),
    "24h": _WindowConfig(timedelta(hours=24), "1 hour", timedelta(hours=1)),
    "7d": _WindowConfig(timedelta(days=7), "1 day", timedelta(days=1)),
}

WINDOWS = tuple(WINDOW_CONFIG)


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


class MetricsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.queries = QuerySessionRepository(db)

    async def summarize(self, *, window: str) -> MetricsSummary:
        cfg = WINDOW_CONFIG.get(window)
        if cfg is None:  # pragma: no cover - the route's Literal guards this
            raise ValueError(f"unknown window {window!r}")

        until = datetime.now(UTC)
        since = until - cfg.lookback
        n_buckets = round(cfg.lookback / cfg.grain)

        agg = await self.queries.window_aggregate(since=since, until=until)
        raw_buckets = await self.queries.bucket_aggregate(
            since=since, until=until, grain=cfg.grain_sql, origin=since
        )

        total = int(agg.get("total") or 0)
        failed = int(agg.get("failed") or 0)
        abstained = int(agg.get("abstained") or 0)

        latency = LatencyPercentiles(
            p50_ms=_as_float(agg.get("p50")),
            p95_ms=_as_float(agg.get("p95")),
            p99_ms=_as_float(agg.get("p99")),
            count=int(agg.get("latency_count") or 0),
        )

        series = self._fill_series(raw_buckets, since=since, grain=cfg.grain, n=n_buckets)

        minutes = cfg.lookback.total_seconds() / 60
        return MetricsSummary(
            window=window,
            since=since,
            until=until,
            total_queries=total,
            error_rate=(failed / total) if total else 0.0,
            abstain_rate=(abstained / total) if total else 0.0,
            queries_per_min=(total / minutes) if minutes else 0.0,
            latency=latency,
            series=series,
        )

    @staticmethod
    def _fill_series(
        raw_buckets: list[dict[str, Any]],
        *,
        since: datetime,
        grain: timedelta,
        n: int,
    ) -> list[MetricsBucket]:
        """Place sparse DB buckets onto a continuous timeline; empty buckets
        become explicit zeros so the sparkline doesn't connect across gaps."""
        step = grain.total_seconds()
        by_index: dict[int, dict[str, Any]] = {}
        for r in raw_buckets:
            bucket = r["bucket_start"]
            idx = round((bucket - since).total_seconds() / step)
            if 0 <= idx < n:
                by_index[idx] = r

        out: list[MetricsBucket] = []
        for i in range(n):
            start = since + i * grain
            r = by_index.get(i)
            if r is None:
                out.append(
                    MetricsBucket(bucket_start=start, queries=0, errors=0, p95_latency_ms=None)
                )
            else:
                out.append(
                    MetricsBucket(
                        bucket_start=start,
                        queries=int(r.get("queries") or 0),
                        errors=int(r.get("errors") or 0),
                        p95_latency_ms=_as_float(r.get("p95")),
                    )
                )
        return out
