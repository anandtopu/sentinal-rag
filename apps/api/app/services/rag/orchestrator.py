"""Orchestrator — composes the per-stage pipeline.

The class is intentionally a thin coordinator: stage construction in
``__init__``, sequential dispatch in ``run``. Every concern (retrieval,
rerank, context, prompt, budget, generation, grounding, persistence,
audit, metrics) lives in its own stage module.
"""

from __future__ import annotations

import contextlib
import time
from decimal import Decimal
from uuid import UUID

from sentinelrag_shared.audit import (
    AuditService,
    DualWriteAuditService,
    PostgresAuditSink,
)
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.evaluation.grounding import Judge, NliBackend
from sentinelrag_shared.feature_flags import FeatureFlagClient
from sentinelrag_shared.llm import (
    GeneratorTimeoutError,
    LiteLLMEmbedder,
    NoOpReranker,
    Reranker,
)
from sentinelrag_shared.retrieval import AccessFilter
from sentinelrag_shared.telemetry import (
    record_grounding,
    record_llm_cost,
    record_query_completed,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import TenantBudgetRepository
from app.services.budget_reservation import BudgetReservationService
from app.services.cost_service import CostService
from app.services.rag.client import InProcessRetrievalClient, RetrievalClient
from app.services.rag.stages.audit import AuditStage
from app.services.rag.stages.budget import BudgetStage
from app.services.rag.stages.context_assembly import ContextAssemblyStage
from app.services.rag.stages.generation import GenerationStage
from app.services.rag.stages.grounding import GroundingStage
from app.services.rag.stages.persistence import PersistenceStage
from app.services.rag.stages.prompt import PromptStage
from app.services.rag.stages.rerank import RerankStage
from app.services.rag.stages.retrieval import RetrievalStage
from app.services.rag.stages.session import SessionStage
from app.services.rag.types import (
    ABSTAIN_ANSWER,
    GenerationConfig,
    QueryContext,
    QueryOptions,
    QueryResult,
    RetrievalConfig,
)


class Orchestrator:
    """End-to-end RAG pipeline as a coordinator over stages."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_model: str,
        ollama_base_url: str,
        access_filter: AccessFilter | None = None,
        reranker: Reranker | None = None,
        cost_service: CostService | None = None,
        audit_service: AuditService | None = None,
        retrieval_client: RetrievalClient | None = None,
        nli_backend: NliBackend | None = None,
        judge: Judge | None = None,
        flag_client: FeatureFlagClient | None = None,
        generation_timeout_seconds: float = 60.0,
        budget_reservations: BudgetReservationService | None = None,
        embedder: LiteLLMEmbedder | None = None,
    ) -> None:
        self._session = session
        self._embedding_model = embedding_model
        self._ollama_base_url = ollama_base_url
        self._access_filter = access_filter or AccessFilter()
        self._reranker = reranker or NoOpReranker()
        # R3.S5: CostService consults the reservations service inside
        # ``check_budget``; we pass the same instance into BudgetStage
        # for the reserve side.
        self._budget_reservations = budget_reservations
        self._cost_service = cost_service or CostService(
            TenantBudgetRepository(session),
            reservations=budget_reservations,
        )
        self._audit_service = audit_service or DualWriteAuditService(
            primary=PostgresAuditSink(session)
        )
        # The retrieval client may be DI'd (R4 HttpRetrievalClient) but we
        # default to the in-process impl built from the shared library.
        # The embedder is created per request inside ``run`` so the
        # ollama-vs-cloud heuristic still applies; the in-process client
        # gets wired in once the embedder exists.
        self._retrieval_client_override = retrieval_client
        # Cascade adapters: passing None lets ``GroundingStage`` install
        # its own NoOp defaults (judge stays "skipped" until a real one
        # is wired).
        self._nli_backend = nli_backend
        self._judge = judge
        self._flag_client = flag_client
        self._generation_timeout_seconds = generation_timeout_seconds
        # R3.S6: when the route hoists the embedder onto ``app.state`` we
        # use that instance and skip per-request construction. The
        # Temporal worker path leaves this None so it can rebuild per
        # call with a possibly different model alias.
        self._embedder_override = embedder

    async def run(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        retrieval: RetrievalConfig,
        generation: GenerationConfig,
        options: QueryOptions,
    ) -> QueryResult:
        # Use the process-singleton embedder when DI'd (R3.S6); fall
        # back to per-request construction for callers that haven't
        # hoisted theirs to app.state (e.g. Temporal worker, which
        # picks the embedding model per evaluation run).
        embedder = self._embedder_override or LiteLLMEmbedder(
            model_name=self._embedding_model,
            api_base=(
                self._ollama_base_url
                if self._embedding_model.startswith("ollama/")
                else None
            ),
        )
        retrieval_client = self._retrieval_client_override or InProcessRetrievalClient(
            session=self._session,
            embedder=embedder,
            access_filter=self._access_filter,
        )

        ctx = QueryContext(
            query=query,
            auth=auth,
            collection_ids=collection_ids,
            retrieval_cfg=retrieval,
            generation_cfg=generation,
            options=options,
            embedder=embedder,
            ollama_base_url=self._ollama_base_url,
        )

        session_stage = SessionStage(self._session)
        retrieval_stage = RetrievalStage(self._session, retrieval_client)
        rerank_stage = RerankStage(self._session, self._reranker)
        context_stage = ContextAssemblyStage()
        prompt_stage = PromptStage(self._session)
        budget_stage = BudgetStage(
            self._cost_service,
            self._audit_service,
            budget_reservations=self._budget_reservations,
            reservation_ttl_seconds=self._generation_timeout_seconds,
        )
        generation_stage = GenerationStage(
            request_timeout_seconds=self._generation_timeout_seconds,
        )
        grounding_stage = GroundingStage(
            nli_backend=self._nli_backend,
            judge=self._judge,
            flag_client=self._flag_client,
        )
        persistence_stage = PersistenceStage(self._session)
        audit_stage = AuditStage(self._audit_service)

        try:
            await session_stage.open(ctx)
            await retrieval_stage.run(ctx)
            await rerank_stage.run(ctx)
            await context_stage.run(ctx)
            await prompt_stage.run(ctx)

            if not ctx.reranked and ctx.options.abstain_if_unsupported:
                # Short-circuit: skip budget gate + generation entirely.
                ctx.answer_text = ABSTAIN_ANSWER
                ctx.effective_model = ctx.generation_cfg.model
                ctx.gen_usage = None
                ctx.gen_cost = Decimal("0")
                ctx.input_tokens = 0
                ctx.output_tokens = 0
            else:
                await budget_stage.run(ctx)  # may DOWNGRADE or raise on DENY
                await generation_stage.run(ctx)

            await grounding_stage.run(ctx)
            await persistence_stage.run(ctx)
            await self._finalize_success(ctx, session_stage, audit_stage)
            return ctx.to_query_result()

        except Exception as exc:
            ctx.latency_ms = int((time.perf_counter() - ctx.start_time) * 1000)
            error_message = str(exc)[:500]
            # R3.S4: classify provider timeouts so audit dashboards can
            # split them out from generic internal errors.
            reason = (
                "provider_timeout"
                if isinstance(exc, GeneratorTimeoutError)
                else "internal_error"
            )
            with contextlib.suppress(Exception):
                await session_stage.close(
                    ctx, status="failed", error_message=error_message
                )
            record_query_completed(status="failed", latency_ms=ctx.latency_ms)
            # Audit even on failure — the trail is the point. Best-effort:
            # never mask the original exception with a secondary write
            # failure. The daily reconciliation job (Phase 6.5) catches
            # any missed audit rows.
            with contextlib.suppress(Exception):
                await audit_stage.record_query_failed(
                    ctx, error=error_message, reason=reason
                )
            # R3.S5: settle the reservation on the failure path so a
            # stuck provider doesn't lock the tenant's budget for
            # ``timeout + cushion`` seconds.
            with contextlib.suppress(Exception):
                await self._release_reservation_if_any(ctx)
            raise

    async def _finalize_success(
        self,
        ctx: QueryContext,
        session_stage: SessionStage,
        audit_stage: AuditStage,
    ) -> None:
        """Close the session row + emit terminal metrics + audit + release.

        Extracted from ``run`` so the success path stays at one statement-
        density level. All work is best-effort except the session close
        and the QueryResult return (which the caller owns).
        """
        ctx.latency_ms = int((time.perf_counter() - ctx.start_time) * 1000)
        terminal_status = "completed" if ctx.reranked else "abstained"
        await session_stage.close(ctx, status=terminal_status)

        record_query_completed(status=terminal_status, latency_ms=ctx.latency_ms)
        if ctx.grounding_score is not None:
            record_grounding(ctx.grounding_score)
        if ctx.gen_usage is not None and ctx.gen_cost > 0:
            record_llm_cost(
                provider=ctx.gen_usage.provider,
                cost_usd=float(ctx.gen_cost),
            )
        await audit_stage.record_query_executed(ctx)
        # R3.S5: actual cost is already booked via PersistenceStage's
        # usage_records write, so the reservation is just cleanup here.
        await self._release_reservation_if_any(ctx)

    async def _release_reservation_if_any(self, ctx: QueryContext) -> None:
        """Idempotent — safe to call on every exit path."""
        if self._budget_reservations is None:
            return
        if ctx.query_session_id is None:
            return
        if ctx.budget_reservation_amount_usd is None:
            return
        await self._budget_reservations.release(
            tenant_id=ctx.auth.tenant_id,
            request_id=ctx.query_session_id,
        )
