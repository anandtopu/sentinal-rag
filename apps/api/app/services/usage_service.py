"""Usage / cost summary service (ADR-0039).

Read-model over ``usage_records`` + ``tenant_budgets``. Picks the reporting
window (active budget period, else calendar month-to-date), sums spend, and
gap-fills a daily cost series. Period selection + gap-fill live here so they're
unit-testable with fake repositories; raw SQL stays in the repositories.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.budgets import TenantBudgetRepository
from app.db.repositories.usage_records import UsageRecordRepository
from app.schemas.usage import UsageBucket, UsageBudget, UsageSummary


def _day_key(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


class UsageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.budgets = TenantBudgetRepository(db)
        self.usage = UsageRecordRepository(db)

    async def summarize(self, *, tenant_id: UUID) -> UsageSummary:
        until = datetime.now(UTC)
        budget = await self.budgets.get_active(tenant_id)

        if budget is not None:
            since = budget.current_period_start
            period = "budget"
        else:
            since = until.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period = "month-to-date"

        agg = await self.usage.summarize(since=since, until=until)
        total_cost = float(agg.get("total_cost") or 0)
        daily = await self.usage.daily_series(since=since, until=until)
        series = self._fill_daily(daily, since=since, until=until)

        budget_block: UsageBudget | None = None
        utilization: float | None = None
        if budget is not None:
            limit = float(budget.limit_usd)
            budget_block = UsageBudget(
                limit_usd=limit,
                soft_threshold_pct=budget.soft_threshold_pct,
                hard_threshold_pct=budget.hard_threshold_pct,
                period_type=budget.period_type,
                period_start=budget.current_period_start,
                period_end=budget.current_period_end,
            )
            utilization = (total_cost / limit * 100) if limit > 0 else None

        return UsageSummary(
            period=period,
            since=since,
            until=until,
            total_cost_usd=total_cost,
            input_tokens=int(agg.get("input_tokens") or 0),
            output_tokens=int(agg.get("output_tokens") or 0),
            records=int(agg.get("records") or 0),
            budget=budget_block,
            budget_utilization_pct=utilization,
            series=series,
        )

    @staticmethod
    def _fill_daily(
        rows: list[dict[str, Any]], *, since: datetime, until: datetime
    ) -> list[UsageBucket]:
        """One UTC-day bucket per calendar day in [since, until]; empty days
        become explicit 0.0 so the sparkline doesn't connect across gaps."""
        by_date = {_day_key(r["day"]): float(r.get("cost") or 0) for r in rows}
        out: list[UsageBucket] = []
        day = since.date()
        end = until.date()
        while day <= end:
            out.append(
                UsageBucket(
                    bucket_start=datetime(day.year, day.month, day.day, tzinfo=UTC),
                    cost_usd=by_date.get(day, 0.0),
                )
            )
            day += timedelta(days=1)
        return out
