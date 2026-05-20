"""Unit tests for MetricsService (ADR-0038).

Cover the shaping logic — window→bucket mapping, rate math, percentile
passthrough, empty-window degradation, and series gap-fill — with a duck-typed
fake repository so no Postgres is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from app.schemas.metrics import MetricsBucket
from app.services.metrics_service import WINDOW_CONFIG, WINDOWS, MetricsService
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_BUCKETS = {"1h": 12, "24h": 24, "7d": 7}


class FakeQueryRepo:
    """Stand-in for QuerySessionRepository — only the two aggregate methods
    MetricsService consumes."""

    def __init__(self, *, agg: dict[str, Any], buckets: list[dict[str, Any]]) -> None:
        self._agg = agg
        self._buckets = buckets
        self.window_args: dict[str, Any] | None = None
        self.bucket_args: dict[str, Any] | None = None

    async def window_aggregate(self, *, since: datetime, until: datetime) -> dict[str, Any]:
        self.window_args = {"since": since, "until": until}
        return self._agg

    async def bucket_aggregate(
        self, *, since: datetime, until: datetime, grain: str, origin: datetime
    ) -> list[dict[str, Any]]:
        self.bucket_args = {"since": since, "until": until, "grain": grain, "origin": origin}
        return self._buckets


def _service(*, agg: dict[str, Any], buckets: list[dict[str, Any]]) -> MetricsService:
    svc = MetricsService(db=cast(AsyncSession, object()))
    svc.queries = cast(Any, FakeQueryRepo(agg=agg, buckets=buckets))
    return svc


_ZERO_AGG = {
    "total": 0,
    "failed": 0,
    "abstained": 0,
    "latency_count": 0,
    "p50": None,
    "p95": None,
    "p99": None,
}


@pytest.mark.unit
def test_window_config_bucket_counts() -> None:
    assert set(WINDOWS) == {"1h", "24h", "7d"}
    for window, cfg in WINDOW_CONFIG.items():
        assert round(cfg.lookback / cfg.grain) == EXPECTED_BUCKETS[window]
        assert cfg.grain_sql  # non-empty interval literal for date_bin


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_computes_rates_and_percentiles() -> None:
    agg = {
        "total": 10,
        "failed": 2,
        "abstained": 1,
        "latency_count": 7,
        "p50": 200.0,
        "p95": 412.0,
        "p99": 900.0,
    }
    svc = _service(agg=agg, buckets=[])
    summary = await svc.summarize(window="24h")

    assert summary.window == "24h"
    assert summary.total_queries == 10
    assert summary.error_rate == pytest.approx(0.2)
    assert summary.abstain_rate == pytest.approx(0.1)
    assert summary.queries_per_min == pytest.approx(10 / 1440)
    assert summary.latency.p50_ms == 200.0
    assert summary.latency.p95_ms == 412.0
    assert summary.latency.p99_ms == 900.0
    assert summary.latency.count == 7
    # 24h @ 1h grain → 24 buckets; empty repo → all gap-filled zeros.
    assert len(summary.series) == EXPECTED_BUCKETS["24h"]
    assert all(b.queries == 0 and b.p95_latency_ms is None for b in summary.series)
    # until - since spans exactly the window.
    assert summary.until - summary.since == timedelta(hours=24)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_empty_window_degrades_to_zeros_and_none() -> None:
    svc = _service(agg=dict(_ZERO_AGG), buckets=[])
    summary = await svc.summarize(window="1h")

    assert summary.total_queries == 0
    assert summary.error_rate == 0.0
    assert summary.abstain_rate == 0.0
    assert summary.queries_per_min == 0.0
    assert summary.latency.p50_ms is None
    assert summary.latency.p95_ms is None
    assert summary.latency.count == 0
    assert len(summary.series) == EXPECTED_BUCKETS["1h"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_passes_grain_and_window_to_repo() -> None:
    svc = _service(agg=dict(_ZERO_AGG), buckets=[])
    await svc.summarize(window="7d")
    repo = cast(FakeQueryRepo, svc.queries)
    assert repo.bucket_args is not None
    assert repo.bucket_args["grain"] == "1 day"
    # The bucket query's origin is the window start, so date_bin aligns to it.
    assert repo.bucket_args["origin"] == repo.bucket_args["since"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_unknown_window_raises() -> None:
    svc = _service(agg=dict(_ZERO_AGG), buckets=[])
    with pytest.raises(ValueError, match="unknown window"):
        await svc.summarize(window="nope")


@pytest.mark.unit
def test_fill_series_places_buckets_by_index_and_ignores_out_of_range() -> None:
    since = datetime(2026, 5, 20, 0, 0, tzinfo=UTC)
    grain = timedelta(hours=1)
    buckets = [
        {"bucket_start": since, "queries": 5, "errors": 1, "p95": 300.0},
        {"bucket_start": since + 2 * grain, "queries": 8, "errors": 0, "p95": 410.0},
        # Out of range (index 9 with n=3) → must be dropped, not crash.
        {"bucket_start": since + 9 * grain, "queries": 99, "errors": 9, "p95": 1.0},
    ]
    series = MetricsService._fill_series(buckets, since=since, grain=grain, n=3)

    assert [b.bucket_start for b in series] == [since, since + grain, since + 2 * grain]
    assert series[0] == MetricsBucket(
        bucket_start=since, queries=5, errors=1, p95_latency_ms=300.0
    )
    # Gap-filled middle bucket.
    assert series[1].queries == 0
    assert series[1].errors == 0
    assert series[1].p95_latency_ms is None
    assert series[2].queries == 8
    assert series[2].p95_latency_ms == 410.0
