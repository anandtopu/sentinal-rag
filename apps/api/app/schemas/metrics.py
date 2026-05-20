"""Schemas for the operational metrics summary endpoint (ADR-0038).

Per-tenant read-model over ``query_sessions``: scalar summary (percentiles,
rates) for the topbar/dashboard tiles plus a gap-filled time series for the
sparkline. API-only response shapes, so they extend ``APIModel`` rather than
the cross-service ``Contract`` base (ADR-0009).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class LatencyPercentiles(APIModel):
    """Query wall-clock latency percentiles over the window (ms)."""

    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    # Number of in-window queries that carried a latency (terminal, non-null).
    count: int = Field(..., ge=0)


class MetricsBucket(APIModel):
    """One time bucket of the sparkline series."""

    bucket_start: datetime
    queries: int = Field(..., ge=0)
    errors: int = Field(..., ge=0)
    p95_latency_ms: float | None


class MetricsSummary(APIModel):
    """Per-tenant query-activity summary over a fixed window."""

    window: str
    since: datetime
    until: datetime
    total_queries: int = Field(..., ge=0)
    error_rate: float = Field(..., ge=0, le=1)
    abstain_rate: float = Field(..., ge=0, le=1)
    queries_per_min: float = Field(..., ge=0)
    latency: LatencyPercentiles
    series: list[MetricsBucket]
