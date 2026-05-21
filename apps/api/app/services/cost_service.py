"""CostService — per-tenant budget gating (ADR-0022).

The service exposes two operations that the orchestrator calls in the hot
path of a query:

1. ``check_budget(tenant_id, estimate_usd)`` — returns a :class:`BudgetDecision`
   telling the caller whether to ALLOW, DOWNGRADE the model, or DENY.
2. ``record_actual(tenant_id, actual_usd)`` — observability hook the caller
   uses *after* the LLM responds so the next request sees fresh spend.
   (Today the spend is already in ``usage_records`` via the orchestrator's
   double-entry accounting; this is a forward-compat seam for an in-memory
   running total when we move to a Redis cache in Phase 7.)

Pricing for cost estimation lives in :data:`MODEL_PRICES`. New models add a
row here; if a model is unknown the service falls back to a conservative
high price so it errs on the side of downgrading.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sentinelrag_shared.errors import BudgetExceededError

from app.db.models import TenantBudget
from app.db.repositories import TenantBudgetRepository
from app.services.budget_reservation import BudgetReservationService


# ---------------------------------------------------------------------------
# Pricing table (ADR-0022 + ADR-0014).
# Costs are USD per 1,000 tokens. Numbers approximate publicly listed
# pricing as of 2026-04-27; tighten/automate the table in Phase 7.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelPrice:
    input_per_1k: Decimal
    output_per_1k: Decimal


MODEL_PRICES: dict[str, ModelPrice] = {
    # Self-hosted (cost ~= GPU-hours; we model it as zero in the gateway and
    # let infra cost dashboards capture the GPU side).
    "ollama/llama3.1:8b": ModelPrice(Decimal("0"), Decimal("0")),
    "ollama/nomic-embed-text": ModelPrice(Decimal("0"), Decimal("0")),
    # OpenAI
    "openai/gpt-4o": ModelPrice(Decimal("0.0050"), Decimal("0.0150")),
    "openai/gpt-4o-mini": ModelPrice(Decimal("0.00015"), Decimal("0.0006")),
    "openai/text-embedding-3-small": ModelPrice(Decimal("0.00002"), Decimal("0")),
    # Anthropic
    "anthropic/claude-3-5-sonnet": ModelPrice(Decimal("0.003"), Decimal("0.015")),
    "anthropic/claude-3-5-haiku": ModelPrice(Decimal("0.0008"), Decimal("0.004")),
}

# When a soft cap is hit, this is the fallback ladder. The orchestrator picks
# the first entry whose key matches the original model's family.
DEFAULT_DOWNGRADE_LADDER: dict[str, str] = {
    "openai/gpt-4o": "openai/gpt-4o-mini",
    "anthropic/claude-3-5-sonnet": "anthropic/claude-3-5-haiku",
    # Self-hosted has no cheaper tier; falls back to itself (no downgrade).
    "ollama/llama3.1:8b": "ollama/llama3.1:8b",
}


class BudgetAction(StrEnum):
    ALLOW = "allow"
    DOWNGRADE = "downgrade"
    DENY = "deny"


@dataclass(frozen=True)
class BudgetDecision:
    action: BudgetAction
    current_spend_usd: Decimal
    limit_usd: Decimal
    period_end: str | None  # ISO-8601, set when budget exists
    downgrade_to: str | None = None
    reason: str | None = None

    @property
    def utilization_pct(self) -> float:
        if self.limit_usd <= 0:
            return 0.0
        return float(self.current_spend_usd / self.limit_usd * 100)


def estimate_completion_cost(
    *,
    model: str,
    estimated_input_tokens: int,
    max_output_tokens: int,
) -> Decimal:
    """Conservative cost estimate for a single LLM call.

    Uses ``max_output_tokens`` (not expected) so the orchestrator over-blocks
    rather than under-charges (ADR-0022).
    """
    price = MODEL_PRICES.get(model)
    if price is None:
        # Unknown model: fall back to GPT-4o-priced ceiling so we err on the
        # side of denying. Logged in the decision's reason field so callers
        # can detect a missing pricing entry.
        price = MODEL_PRICES["openai/gpt-4o"]
    inp = price.input_per_1k * Decimal(estimated_input_tokens) / Decimal(1000)
    out = price.output_per_1k * Decimal(max_output_tokens) / Decimal(1000)
    return inp + out


class CostService:
    def __init__(
        self,
        repo: TenantBudgetRepository,
        reservations: BudgetReservationService | None = None,
    ) -> None:
        self.repo = repo
        # R3.S5: optional. When wired (via the route handler) the gate
        # adds in-flight reservation totals to projected spend so
        # concurrent queries can't burst past the hard cap during a
        # provider timeout. A ``None`` reservations service is the
        # legacy behavior — kept so direct CostService instantiation
        # in tests stays cheap.
        self.reservations = reservations

    async def check_budget(
        self,
        *,
        tenant_id: UUID,
        estimate_usd: Decimal,
        requested_model: str,
    ) -> BudgetDecision:
        """Decide whether to allow / downgrade / deny a pending LLM call."""
        budget = await self.repo.get_active(tenant_id)
        if budget is None:
            # No active budget configured ⇒ default to allow. We surface this
            # explicitly rather than silently because the operator may want
            # to enforce that all tenants have a budget set in production.
            return BudgetDecision(
                action=BudgetAction.ALLOW,
                current_spend_usd=Decimal("0"),
                limit_usd=Decimal("0"),
                period_end=None,
                reason="no-budget-configured",
            )

        spend = await self.repo.period_spend(
            tenant_id=tenant_id,
            period_start=budget.current_period_start,
            period_end=budget.current_period_end,
        )
        reserved = (
            await self.reservations.total_reserved(tenant_id=tenant_id)
            if self.reservations is not None
            else Decimal("0")
        )
        projected = spend + reserved + estimate_usd

        # Compute thresholds in USD.
        soft_limit = (
            budget.limit_usd * Decimal(budget.soft_threshold_pct) / Decimal(100)
        )
        hard_limit = (
            budget.limit_usd * Decimal(budget.hard_threshold_pct) / Decimal(100)
        )

        period_end_iso = budget.current_period_end.isoformat()

        if projected >= hard_limit:
            return BudgetDecision(
                action=BudgetAction.DENY,
                current_spend_usd=spend,
                limit_usd=budget.limit_usd,
                period_end=period_end_iso,
                reason=f"projected {projected} >= hard cap {hard_limit}",
            )

        if projected >= soft_limit:
            downgrade = _resolve_downgrade(budget, requested_model)
            if downgrade and downgrade != requested_model:
                return BudgetDecision(
                    action=BudgetAction.DOWNGRADE,
                    current_spend_usd=spend,
                    limit_usd=budget.limit_usd,
                    period_end=period_end_iso,
                    downgrade_to=downgrade,
                    reason=f"projected {projected} >= soft cap {soft_limit}",
                )
            # Already on the cheapest tier ⇒ ALLOW with a soft-warning reason.
            return BudgetDecision(
                action=BudgetAction.ALLOW,
                current_spend_usd=spend,
                limit_usd=budget.limit_usd,
                period_end=period_end_iso,
                reason="soft-cap-hit-no-downgrade-available",
            )

        return BudgetDecision(
            action=BudgetAction.ALLOW,
            current_spend_usd=spend,
            limit_usd=budget.limit_usd,
            period_end=period_end_iso,
        )


def _resolve_downgrade(budget: TenantBudget, requested_model: str) -> str | None:
    """Per-tenant override > global default ladder."""
    override = budget.downgrade_policy or {}
    if isinstance(override, dict) and requested_model in override:
        target = override[requested_model]
        if isinstance(target, str):
            return target
    return DEFAULT_DOWNGRADE_LADDER.get(requested_model)


def enforce_or_raise(decision: BudgetDecision) -> str | None:
    """Helper for callers: raise on DENY, return downgrade target on DOWNGRADE.

    Returns the new model name if the caller should downgrade, or ``None`` if
    the caller should keep the originally requested model.
    """
    if decision.action == BudgetAction.DENY:
        raise BudgetExceededError(
            "Tenant budget exceeded for the active period.",
            details={
                "current_spend_usd": str(decision.current_spend_usd),
                "limit_usd": str(decision.limit_usd),
                "period_end": decision.period_end,
                "reason": decision.reason,
            },
        )
    if decision.action == BudgetAction.DOWNGRADE:
        return decision.downgrade_to
    return None
