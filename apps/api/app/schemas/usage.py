"""Schemas for the usage / cost summary endpoint (ADR-0039).

Per-tenant read-model over ``usage_records`` + ``tenant_budgets``: spend over
the active budget period (or calendar month-to-date), budget context for the
"% of budget" sub, and a daily cost series for the sparkline. Cost is
serialized as ``float`` per the existing API convention.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class UsageBudget(APIModel):
    """Active budget context, when one is configured."""

    limit_usd: float
    soft_threshold_pct: int
    hard_threshold_pct: int
    period_type: str
    period_start: datetime
    period_end: datetime


class UsageBucket(APIModel):
    """One UTC-day of the cost series."""

    bucket_start: datetime
    cost_usd: float


class UsageSummary(APIModel):
    """Per-tenant cost summary for the current period."""

    # "budget" when an active budget defines the window, else "month-to-date".
    period: str
    since: datetime
    until: datetime
    total_cost_usd: float
    input_tokens: int
    output_tokens: int
    records: int
    budget: UsageBudget | None
    budget_utilization_pct: float | None
    series: list[UsageBucket] = Field(default_factory=list)
