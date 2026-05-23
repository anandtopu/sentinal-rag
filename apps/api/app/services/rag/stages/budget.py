"""BudgetStage — per-tenant cost gate (ADR-0022).

Runs *before* generation. On DOWNGRADE the stage rewrites ``ctx.effective_model``;
on DENY it raises ``BudgetExceededError`` after emitting a ``budget.denied``
audit event. Both branches emit a ``budget.*`` audit event before
``enforce_or_raise`` is called so the trail survives rejected requests.
"""

from __future__ import annotations

from decimal import Decimal

from sentinelrag_shared.audit import AuditEvent, AuditService
from sentinelrag_shared.telemetry import record_budget_decision

from app.services.budget_reservation import BudgetReservationService
from app.services.cost_service import (
    BudgetAction,
    CostService,
    enforce_or_raise,
    estimate_completion_cost,
)
from app.services.rag._helpers import fill_prompt, token_count
from app.services.rag.types import QueryContext


class BudgetStage:
    def __init__(
        self,
        cost_service: CostService,
        audit_service: AuditService,
        budget_reservations: BudgetReservationService | None = None,
        reservation_ttl_seconds: float = 60.0,
    ) -> None:
        self._cost_service = cost_service
        self._audit_service = audit_service
        # R3.S5: optional — when wired, the gate's ALLOW/DOWNGRADE
        # branches also reserve the projected spend in Redis so
        # concurrent requests can't burst past the cap during a
        # provider timeout. Release is the orchestrator's job (it
        # owns the success + failure paths).
        self._reservations = budget_reservations
        self._reservation_ttl_seconds = reservation_ttl_seconds

    async def run(self, ctx: QueryContext) -> None:
        if ctx.resolved_prompt is None:
            msg = "BudgetStage requires PromptStage to have resolved a prompt first."
            raise RuntimeError(msg)
        if ctx.query_session_id is None:
            msg = "BudgetStage requires SessionStage.open to have run first."
            raise RuntimeError(msg)

        user_prompt = fill_prompt(
            ctx.resolved_prompt.user_prompt_template,
            query=ctx.query.strip(),
            context=ctx.context_text,
        )
        estimated_input_tokens = token_count(
            model=ctx.generation_cfg.model,
            text=ctx.resolved_prompt.system_prompt + "\n" + user_prompt,
        )
        estimate = estimate_completion_cost(
            model=ctx.generation_cfg.model,
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=ctx.generation_cfg.max_tokens,
        )
        # R3.S1: roll the embedding cost into the budget estimate so the
        # gate sees the actual cumulative spend a query will book, not
        # just the LLM-completion slice.
        if (
            ctx.embedding_usage is not None
            and ctx.embedding_usage.total_cost_usd is not None
        ):
            estimate += ctx.embedding_usage.total_cost_usd
        decision = await self._cost_service.check_budget(
            tenant_id=ctx.auth.tenant_id,
            estimate_usd=estimate,
            requested_model=ctx.generation_cfg.model,
        )
        ctx.budget_decision = decision

        record_budget_decision(action=decision.action.value)

        if decision.action != BudgetAction.ALLOW:
            await self._record_audit(ctx=ctx, decision_estimate_usd=estimate)

        downgrade_target = enforce_or_raise(decision)
        ctx.effective_model = downgrade_target or ctx.generation_cfg.model
        # R3.S5: after the gate clears (DENY raised above), reserve
        # the projected spend so concurrent requests in the same
        # tenant see this charge in ``check_budget``'s ``reserved``
        # total. ``query_session_id`` is non-None here — the assert at
        # the top of ``run`` already established that.
        if self._reservations is not None:
            ctx.budget_reservation_amount_usd = estimate
            await self._reservations.reserve(
                tenant_id=ctx.auth.tenant_id,
                request_id=ctx.query_session_id,
                amount_usd=estimate,
                ttl_seconds=self._reservation_ttl_seconds,
            )

    async def _record_audit(
        self,
        *,
        ctx: QueryContext,
        decision_estimate_usd: Decimal,
    ) -> None:
        assert ctx.budget_decision is not None
        assert ctx.query_session_id is not None
        decision = ctx.budget_decision
        event_type = (
            "budget.denied"
            if decision.action == BudgetAction.DENY
            else "budget.downgraded"
        )
        await self._audit_service.record(
            AuditEvent(
                tenant_id=ctx.auth.tenant_id,
                actor_user_id=ctx.auth.user_id,
                event_type=event_type,
                resource_type="query_session",
                resource_id=ctx.query_session_id,
                action="execute",
                metadata={
                    "requested_model": ctx.generation_cfg.model,
                    "downgrade_to": decision.downgrade_to,
                    "estimate_usd": str(decision_estimate_usd),
                    "current_spend_usd": str(decision.current_spend_usd),
                    "limit_usd": str(decision.limit_usd),
                    "reason": decision.reason,
                },
            )
        )
