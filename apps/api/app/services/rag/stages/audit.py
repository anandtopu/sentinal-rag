"""AuditStage — emits ``query.executed`` and ``query.failed`` events.

``budget.denied`` / ``budget.downgraded`` events are emitted from
:class:`~app.services.rag.stages.budget.BudgetStage` because the audit must
land *before* ``enforce_or_raise`` raises on DENY.
"""

from __future__ import annotations

from sentinelrag_shared.audit import AuditEvent, AuditService

from app.services.rag.types import QueryContext


class AuditStage:
    def __init__(self, audit_service: AuditService) -> None:
        self._audit_service = audit_service

    async def record_query_executed(self, ctx: QueryContext) -> None:
        if ctx.query_session_id is None:
            msg = "AuditStage requires SessionStage.open to have run first."
            raise RuntimeError(msg)
        await self._audit_service.record(
            AuditEvent(
                tenant_id=ctx.auth.tenant_id,
                actor_user_id=ctx.auth.user_id,
                event_type="query.executed",
                resource_type="query_session",
                resource_id=ctx.query_session_id,
                action="execute",
                metadata={
                    "model_requested": ctx.generation_cfg.model,
                    "model_effective": ctx.effective_model,
                    "input_tokens": ctx.input_tokens,
                    "output_tokens": ctx.output_tokens,
                    "cost_usd": str(ctx.gen_cost),
                    "latency_ms": ctx.latency_ms,
                    "abstained": not ctx.reranked,
                },
            )
        )

    async def record_query_failed(self, ctx: QueryContext, *, error: str) -> None:
        if ctx.query_session_id is None:
            # If the session row never opened, there's nothing useful to attach
            # an audit event to. Skip — the failure log + metric capture it.
            return
        await self._audit_service.record(
            AuditEvent(
                tenant_id=ctx.auth.tenant_id,
                actor_user_id=ctx.auth.user_id,
                event_type="query.failed",
                resource_type="query_session",
                resource_id=ctx.query_session_id,
                action="execute",
                metadata={
                    "error": error[:500],
                    "latency_ms": ctx.latency_ms,
                },
            )
        )
