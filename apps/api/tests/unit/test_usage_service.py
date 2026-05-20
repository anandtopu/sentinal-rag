"""Unit tests for UsageService (ADR-0039).

Cover period selection (budget window vs calendar month-to-date), utilization
math, Decimal→float, and daily-series gap-fill with duck-typed fake repos so
no Postgres is needed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.services.usage_service import UsageService
from sqlalchemy.ext.asyncio import AsyncSession


class FakeBudgetRepo:
    def __init__(self, budget: Any) -> None:
        self._budget = budget

    async def get_active(self, tenant_id: Any) -> Any:
        return self._budget


class FakeUsageRepo:
    def __init__(self, *, agg: dict[str, Any], daily: list[dict[str, Any]]) -> None:
        self._agg = agg
        self._daily = daily
        self.summarize_args: dict[str, Any] | None = None

    async def summarize(self, *, since: datetime, until: datetime) -> dict[str, Any]:
        self.summarize_args = {"since": since, "until": until}
        return self._agg

    async def daily_series(self, *, since: datetime, until: datetime) -> list[dict[str, Any]]:
        return self._daily


def _service(*, budget: Any, agg: dict[str, Any], daily: list[dict[str, Any]]) -> UsageService:
    svc = UsageService(db=cast(AsyncSession, object()))
    svc.budgets = cast(Any, FakeBudgetRepo(budget))
    svc.usage = cast(Any, FakeUsageRepo(agg=agg, daily=daily))
    return svc


def _budget(*, limit: str = "270", soft: int = 80, hard: int = 100) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        current_period_start=now - timedelta(days=5),
        current_period_end=now + timedelta(days=25),
        limit_usd=Decimal(limit),
        soft_threshold_pct=soft,
        hard_threshold_pct=hard,
        period_type="month",
    )


_ZERO_AGG = {"total_cost": Decimal("0"), "input_tokens": 0, "output_tokens": 0, "records": 0}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_period_reports_utilization() -> None:
    agg = {
        "total_cost": Decimal("184.20"),
        "input_tokens": 12_000,
        "output_tokens": 3_400,
        "records": 42,
    }
    svc = _service(budget=_budget(limit="270"), agg=agg, daily=[])
    summary = await svc.summarize(tenant_id="t1")

    assert summary.period == "budget"
    assert summary.total_cost_usd == pytest.approx(184.20)
    assert summary.records == 42
    assert summary.budget is not None
    assert summary.budget.limit_usd == pytest.approx(270.0)
    assert summary.budget_utilization_pct == pytest.approx(184.20 / 270 * 100)
    # The aggregate window starts at the budget period start.
    repo = cast(FakeUsageRepo, svc.usage)
    assert repo.summarize_args is not None
    assert repo.summarize_args["since"] < repo.summarize_args["until"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_budget_falls_back_to_calendar_month_to_date() -> None:
    agg = {
        "total_cost": Decimal("12.5"),
        "input_tokens": 100,
        "output_tokens": 50,
        "records": 3,
    }
    svc = _service(budget=None, agg=agg, daily=[])
    summary = await svc.summarize(tenant_id="t1")

    assert summary.period == "month-to-date"
    assert summary.budget is None
    assert summary.budget_utilization_pct is None
    assert summary.total_cost_usd == pytest.approx(12.5)
    # since is the 1st of the current month → one bucket per day up to today.
    assert summary.since.day == 1
    assert len(summary.series) == datetime.now(UTC).day


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_limit_budget_yields_no_utilization() -> None:
    svc = _service(budget=_budget(limit="0"), agg=dict(_ZERO_AGG), daily=[])
    summary = await svc.summarize(tenant_id="t1")
    assert summary.budget is not None
    assert summary.budget_utilization_pct is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_usage_degrades_to_zero() -> None:
    svc = _service(budget=None, agg=dict(_ZERO_AGG), daily=[])
    summary = await svc.summarize(tenant_id="t1")
    assert summary.total_cost_usd == 0.0
    assert summary.records == 0
    assert all(b.cost_usd == 0.0 for b in summary.series)


@pytest.mark.unit
def test_fill_daily_places_costs_and_gap_fills() -> None:
    since = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    until = datetime(2026, 5, 3, 8, 0, tzinfo=UTC)
    rows = [
        {"day": date(2026, 5, 1), "cost": Decimal("1.5")},
        {"day": date(2026, 5, 3), "cost": Decimal("2.0")},
    ]
    series = UsageService._fill_daily(rows, since=since, until=until)

    assert [b.bucket_start for b in series] == [
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 5, 2, tzinfo=UTC),
        datetime(2026, 5, 3, tzinfo=UTC),
    ]
    assert series[0].cost_usd == 1.5
    assert series[1].cost_usd == 0.0  # gap-filled
    assert series[2].cost_usd == 2.0
