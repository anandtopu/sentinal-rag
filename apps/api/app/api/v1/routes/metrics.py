"""Operational metrics routes (ADR-0038).

Per-tenant read-model over ``query_sessions`` powering the console's topbar
ops chips and dashboard latency tile/sparkline.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.session import get_db
from app.schemas.metrics import MetricsSummary
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary)
async def metrics_summary(
    # Metrics summarize the caller's own query activity; reuse the seeded
    # queries:execute permission rather than minting a new one (ADR-0038).
    _ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    window: Annotated[Literal["1h", "24h", "7d"], Query()] = "24h",
) -> MetricsSummary:
    """Latency percentiles, error/abstain rates, and a gap-filled volume
    series over the requested window, scoped to the tenant via RLS."""
    return await MetricsService(db).summarize(window=window)
