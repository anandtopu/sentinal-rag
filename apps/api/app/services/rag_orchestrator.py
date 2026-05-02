"""RagOrchestrator — end-to-end query pipeline with full traceability.

Pipeline (CLAUDE.md architectural pillars #1, #3, #4):

    1. Open ``query_session`` row (status=running).
    2. HybridRetriever — BM25 + vector with RBAC pre-filter (pillar #1).
    3. Persist ``retrieval_results`` for each stage (bm25, vector, hybrid_merge).
    4. Reranker — bge-reranker-v2-m3 by default, reorder + truncate to top_k_rerank.
    5. Persist ``retrieval_results`` for the rerank stage.
    6. Assemble context with citation markers ``[1]``, ``[2]``, ...
    7. Resolve prompt template + version (Phase 4 wires the registry; v1 uses
       a built-in default prompt).
    8. Generator — LiteLLM completion.
    9. Cheap grounding score — token overlap between answer and retrieved
       context (Phase 4 layers full hallucination detection on top).
    10. Persist ``generated_answer`` + ``answer_citations``.
    11. Persist ``usage_records`` for embedding + completion.
    12. Close ``query_session`` (status=completed; latency_ms, total_cost_usd).

Failures: any exception persists ``query_session.status='failed'`` and the
error message; we re-raise so the route handler maps to a 5xx envelope.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sentinelrag_shared.audit import (
    AuditEvent,
    AuditService,
    DualWriteAuditService,
    PostgresAuditSink,
)
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.llm import (
    LiteLLMEmbedder,
    LiteLLMGenerator,
    NoOpReranker,
    RerankCandidate,
    Reranker,
    RerankerError,
)
from sentinelrag_shared.retrieval import (
    AccessFilter,
    Candidate,
    HybridRetrievalResult,
    HybridRetriever,
    PgvectorVectorSearch,
    PostgresFtsKeywordSearch,
    RetrievalStage,
)
from sentinelrag_shared.telemetry import (
    record_budget_decision,
    record_grounding,
    record_llm_cost,
    record_query_completed,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import TenantBudgetRepository
from app.services.cost_service import (
    BudgetAction,
    CostService,
    enforce_or_raise,
    estimate_completion_cost,
)
from app.services.prompt_service import DEFAULT_RAG_PROMPT_NAME, PromptService


@dataclass(slots=True)
class RetrievalConfig:
    mode: str = "hybrid"
    top_k_bm25: int = 20
    top_k_vector: int = 20
    top_k_hybrid: int = 30
    top_k_rerank: int = 8
    ef_search: int | None = None


@dataclass(slots=True)
class GenerationConfig:
    model: str = "ollama/llama3.1:8b"
    temperature: float = 0.1
    max_tokens: int = 800


@dataclass(slots=True)
class QueryOptions:
    include_debug_trace: bool = False
    abstain_if_unsupported: bool = True
    prompt_version_id: UUID | None = None  # explicit prompt version override


@dataclass(slots=True)
class CitationOut:
    citation_id: UUID
    chunk_id: UUID
    document_id: UUID
    citation_index: int
    quoted_text: str | None
    page_number: int | None
    section_title: str | None
    relevance_score: float | None


@dataclass(slots=True)
class QueryResult:
    query_session_id: UUID
    answer: str
    confidence_score: float | None
    grounding_score: float | None
    hallucination_risk_score: float | None
    citations: list[CitationOut]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class RagOrchestrator:
    """End-to-end RAG pipeline with persistence."""

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
    ) -> None:
        self.session = session
        self.embedding_model = embedding_model
        self.ollama_base_url = ollama_base_url
        self.access_filter = access_filter or AccessFilter()
        # In v1 we default to NoOpReranker if a real reranker isn't injected;
        # the route configures ``BgeReranker`` once at app startup. NoOp keeps
        # tests fast.
        self.reranker = reranker or NoOpReranker()
        # Optional: when provided, the orchestrator gates generation on the
        # tenant's active budget (ADR-0022). If None, budget gating is off
        # (e.g. Phase 1 boot smoke tests with no budget rows seeded).
        self.cost_service = cost_service or CostService(
            TenantBudgetRepository(session)
        )
        # Audit (ADR-0016) — defaults to Postgres-only dual-write. The route
        # (or app lifecycle) wires the S3 secondary in production deploys.
        self.audit_service = audit_service or DualWriteAuditService(
            primary=PostgresAuditSink(session)
        )

    async def run(  # noqa: PLR0915 — orchestration intentionally inlines all stages
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        retrieval: RetrievalConfig,
        generation: GenerationConfig,
        options: QueryOptions,
    ) -> QueryResult:
        start_total = time.perf_counter()

        # Resolve embedder + generator from configs.
        embedder = LiteLLMEmbedder(
            model_name=self.embedding_model,
            api_base=self.ollama_base_url
            if self.embedding_model.startswith("ollama/")
            else None,
        )
        generator = LiteLLMGenerator(
            model_name=generation.model,
            api_base=self.ollama_base_url
            if generation.model.startswith("ollama/")
            else None,
        )

        keyword_search = PostgresFtsKeywordSearch(
            session=self.session, access_filter=self.access_filter
        )
        vector_search = PgvectorVectorSearch(
            session=self.session,
            embedder=embedder,
            access_filter=self.access_filter,
        )
        hybrid = HybridRetriever(
            keyword_search=keyword_search,
            vector_search=vector_search,
        )

        # 1. Open query_session.
        query_session_id = await self._open_query_session(
            auth=auth, query=query, collection_ids=collection_ids
        )

        try:
            # 2-3. Retrieve + persist stage results.
            if retrieval.mode == "bm25":
                bm25 = await keyword_search.search(
                    query=query,
                    auth=auth,
                    collection_ids=collection_ids,
                    top_k=retrieval.top_k_bm25,
                )
                hybrid_result = HybridRetrievalResult(
                    bm25_candidates=bm25,
                    vector_candidates=[],
                    merged_candidates=self._as_stage(
                        bm25[: retrieval.top_k_hybrid], RetrievalStage.HYBRID_MERGE
                    ),
                )
            elif retrieval.mode == "vector":
                vector = await vector_search.search(
                    query=query,
                    auth=auth,
                    collection_ids=collection_ids,
                    top_k=retrieval.top_k_vector,
                    ef_search=retrieval.ef_search,
                )
                hybrid_result = HybridRetrievalResult(
                    bm25_candidates=[],
                    vector_candidates=vector,
                    merged_candidates=self._as_stage(
                        vector[: retrieval.top_k_hybrid], RetrievalStage.HYBRID_MERGE
                    ),
                )
            else:
                hybrid_result = await hybrid.retrieve(
                    query=query,
                    auth=auth,
                    collection_ids=collection_ids,
                    top_k_bm25=retrieval.top_k_bm25,
                    top_k_vector=retrieval.top_k_vector,
                    top_k_hybrid=retrieval.top_k_hybrid,
                    ef_search=retrieval.ef_search,
                )
            await self._persist_candidates(
                query_session_id, auth.tenant_id, hybrid_result.bm25_candidates
            )
            await self._persist_candidates(
                query_session_id, auth.tenant_id, hybrid_result.vector_candidates
            )
            await self._persist_candidates(
                query_session_id, auth.tenant_id, hybrid_result.merged_candidates
            )

            # 4-5. Rerank + persist.
            reranked = self._rerank(
                query=query,
                merged=hybrid_result.merged_candidates,
                top_k=retrieval.top_k_rerank,
            )
            await self._persist_candidates(
                query_session_id, auth.tenant_id, reranked
            )

            # 6. Assemble context.
            context_text, citations_for_persist = self._assemble_context(reranked)

            # 7. Resolve prompt (registry → fallback to built-in default).
            prompt_service = PromptService(self.session)
            resolved = await prompt_service.resolve_for_task(
                tenant_id=auth.tenant_id,
                task_type=DEFAULT_RAG_PROMPT_NAME,
                explicit_version_id=options.prompt_version_id,
            )
            system_prompt_resolved = resolved.system_prompt
            user_prompt_template_resolved = resolved.user_prompt_template
            resolved_version_id = resolved.id

            # 8. Generate.
            user_prompt = user_prompt_template_resolved.format(
                query=query.strip(), context=context_text
            )

            # If retrieval returned no candidates and the user opted in to
            # abstention, short-circuit.
            if not reranked and options.abstain_if_unsupported:
                answer_text = (
                    "I do not have enough information in the provided sources "
                    "to answer that confidently."
                )
                gen_usage = None
                gen_cost = Decimal("0")
                input_tokens = 0
                output_tokens = 0
                effective_model = generation.model
            else:
                # 8a. Budget gate (ADR-0022). The estimate uses the
                # constructed prompt size + generation.max_tokens as the
                # over-cap. enforce_or_raise raises BudgetExceededError on
                # DENY (mapped to 402) and returns the downgrade target on
                # DOWNGRADE.
                estimated_input_tokens = _approx_token_count(
                    system_prompt_resolved + "\n" + user_prompt
                )
                estimate = estimate_completion_cost(
                    model=generation.model,
                    estimated_input_tokens=estimated_input_tokens,
                    max_output_tokens=generation.max_tokens,
                )
                decision = await self.cost_service.check_budget(
                    tenant_id=auth.tenant_id,
                    estimate_usd=estimate,
                    requested_model=generation.model,
                )
                # Audit *before* enforce — DENY raises, so the audit write
                # has to happen first or we lose the trail on rejected
                # requests.
                record_budget_decision(action=decision.action.value)
                if decision.action != BudgetAction.ALLOW:
                    await self._record_budget_audit(
                        auth=auth,
                        query_session_id=query_session_id,
                        decision=decision,
                        requested_model=generation.model,
                        estimate_usd=estimate,
                    )
                downgrade_target = enforce_or_raise(decision)
                effective_model = downgrade_target or generation.model
                if downgrade_target and downgrade_target != generation.model:
                    # Re-bind the generator to the downgraded model. Keep the
                    # original ollama_base_url heuristic.
                    generator = LiteLLMGenerator(
                        model_name=effective_model,
                        api_base=self.ollama_base_url
                        if effective_model.startswith("ollama/")
                        else None,
                    )

                gen_result = await generator.complete(
                    system_prompt=system_prompt_resolved,
                    user_prompt=user_prompt,
                    temperature=generation.temperature,
                    max_tokens=generation.max_tokens,
                )
                answer_text = gen_result.text
                gen_usage = gen_result.usage
                gen_cost = gen_usage.total_cost_usd or Decimal("0")
                input_tokens = gen_usage.input_tokens
                output_tokens = gen_usage.output_tokens
                # Decision tagged on for downstream metric / audit emission.
                _ = decision  # kept for Phase 6 metric/audit hooks below

            # 9. Cheap grounding signal — full layered detector lands in Phase 4.
            grounding = _token_overlap_score(answer_text, context_text)

            # 10. Persist generated_answer + citations. ``effective_model``
            # captures any soft-cap downgrade so the trace + audit reflect
            # what actually ran, not what the caller asked for.
            generated_answer_id = await self._persist_generated_answer(
                query_session_id=query_session_id,
                tenant_id=auth.tenant_id,
                answer_text=answer_text,
                model_provider=effective_model.split("/", 1)[0]
                if "/" in effective_model
                else "unknown",
                model_name=effective_model,
                prompt_version_id=resolved_version_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=gen_cost,
                grounding_score=grounding,
            )
            cited_out = await self._persist_citations(
                generated_answer_id=generated_answer_id,
                tenant_id=auth.tenant_id,
                citations=citations_for_persist,
                answer_text=answer_text,
            )

            # 11. Persist usage_records (embedding, completion).
            await self._persist_usage(
                query_session_id=query_session_id,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                usage_type="embedding",
                provider=embedder.model_name.split("/", 1)[0],
                model_name=embedder.model_name,
                # vector_search currently embeds the query inline; tokens not surfaced in v1.
                input_tokens=0,
                output_tokens=0,
                total_cost_usd=Decimal("0"),
            )
            if gen_usage is not None:
                await self._persist_usage(
                    query_session_id=query_session_id,
                    tenant_id=auth.tenant_id,
                    user_id=auth.user_id,
                    usage_type="completion",
                    provider=gen_usage.provider,
                    model_name=gen_usage.model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_cost_usd=gen_cost,
                )

            # 12. Close query_session.
            latency_ms = int((time.perf_counter() - start_total) * 1000)
            total_cost = float(gen_cost)
            await self._close_query_session(
                query_session_id=query_session_id,
                status="completed" if reranked else "abstained",
                latency_ms=latency_ms,
                total_cost_usd=total_cost,
            )

            # 13. Metrics (ADR-0023 / Phase 6).
            terminal_status = "completed" if reranked else "abstained"
            record_query_completed(status=terminal_status, latency_ms=latency_ms)
            if grounding is not None:
                record_grounding(grounding)
            if gen_usage is not None and gen_cost > 0:
                record_llm_cost(
                    provider=gen_usage.provider,
                    cost_usd=float(gen_cost),
                )

            # 14. Audit (ADR-0016) — query.executed.
            await self.audit_service.record(
                AuditEvent(
                    tenant_id=auth.tenant_id,
                    actor_user_id=auth.user_id,
                    event_type="query.executed",
                    resource_type="query_session",
                    resource_id=query_session_id,
                    action="execute",
                    metadata={
                        "model_requested": generation.model,
                        "model_effective": effective_model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": str(gen_cost),
                        "latency_ms": latency_ms,
                        "abstained": not reranked,
                    },
                )
            )

            return QueryResult(
                query_session_id=query_session_id,
                answer=answer_text,
                confidence_score=None,  # Phase 4
                grounding_score=grounding,
                hallucination_risk_score=None,  # Phase 4
                citations=cited_out,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=total_cost,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_total) * 1000)
            await self._close_query_session(
                query_session_id=query_session_id,
                status="failed",
                latency_ms=latency_ms,
                total_cost_usd=0.0,
                error_message=str(exc)[:500],
            )
            record_query_completed(status="failed", latency_ms=latency_ms)
            # Audit even on failure — the trail is the point. Best-effort:
            # if the audit write itself fails, don't mask the original
            # error. We deliberately swallow because the original `exc`
            # is what the caller cares about; the audit miss is tolerable
            # and gets caught by the daily reconciliation job (ADR-0016).
            with contextlib.suppress(Exception):
                await self.audit_service.record(
                    AuditEvent(
                        tenant_id=auth.tenant_id,
                        actor_user_id=auth.user_id,
                        event_type="query.failed",
                        resource_type="query_session",
                        resource_id=query_session_id,
                        action="execute",
                        metadata={
                            "error": str(exc)[:500],
                            "latency_ms": latency_ms,
                        },
                    )
                )
            raise

    # ---------- helpers ----------

    async def _record_budget_audit(
        self,
        *,
        auth: AuthContext,
        query_session_id: UUID,
        decision: Any,  # BudgetDecision; typed as Any to keep import order tidy
        requested_model: str,
        estimate_usd: Decimal,
    ) -> None:
        event_type = (
            "budget.denied" if decision.action == BudgetAction.DENY
            else "budget.downgraded"
        )
        await self.audit_service.record(
            AuditEvent(
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                event_type=event_type,
                resource_type="query_session",
                resource_id=query_session_id,
                action="execute",
                metadata={
                    "requested_model": requested_model,
                    "downgrade_to": decision.downgrade_to,
                    "estimate_usd": str(estimate_usd),
                    "current_spend_usd": str(decision.current_spend_usd),
                    "limit_usd": str(decision.limit_usd),
                    "reason": decision.reason,
                },
            )
        )

    def _rerank(
        self, *, query: str, merged: list[Candidate], top_k: int
    ) -> list[Candidate]:
        if not merged:
            return []
        if top_k <= 0:
            return [
                Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    content=c.content,
                    score=c.score,
                    rank=rank,
                    stage=RetrievalStage.RERANK,
                    page_number=c.page_number,
                    section_title=c.section_title,
                    metadata={**c.metadata, "rerank_disabled": True},
                )
                for rank, c in enumerate(merged, start=1)
            ]
        rerank_inputs = [
            RerankCandidate(chunk_id=str(c.chunk_id), text=c.content) for c in merged
        ]
        try:
            result = self.reranker.rerank(
                query=query, candidates=rerank_inputs, top_k=top_k
            )
        except RerankerError:
            # Degrade: keep merged ordering, truncate.
            return [
                Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    content=c.content,
                    score=c.score,
                    rank=rank,
                    stage=RetrievalStage.RERANK,
                    page_number=c.page_number,
                    section_title=c.section_title,
                    metadata={**c.metadata, "rerank_degraded": True},
                )
                for rank, c in enumerate(merged[:top_k], start=1)
            ]

        out: list[Candidate] = []
        for rank, (idx, score) in enumerate(
            zip(result.indices, result.scores, strict=True), start=1
        ):
            src = merged[idx]
            out.append(
                Candidate(
                    chunk_id=src.chunk_id,
                    document_id=src.document_id,
                    content=src.content,
                    score=score,
                    rank=rank,
                    stage=RetrievalStage.RERANK,
                    page_number=src.page_number,
                    section_title=src.section_title,
                    metadata={**src.metadata, "reranker_model": result.model_name},
                )
            )
        return out

    def _as_stage(
        self, candidates: list[Candidate], stage: RetrievalStage
    ) -> list[Candidate]:
        return [
            Candidate(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                content=c.content,
                score=c.score,
                rank=rank,
                stage=stage,
                page_number=c.page_number,
                section_title=c.section_title,
                metadata=c.metadata,
            )
            for rank, c in enumerate(candidates, start=1)
        ]

    @staticmethod
    def _assemble_context(
        reranked: list[Candidate],
    ) -> tuple[str, list[tuple[int, Candidate]]]:
        """Return (context_block, [(citation_index, candidate), ...])."""
        lines: list[str] = []
        citations: list[tuple[int, Candidate]] = []
        for i, cand in enumerate(reranked, start=1):
            page = (
                f", page {cand.page_number}" if cand.page_number is not None else ""
            )
            section = f" — {cand.section_title}" if cand.section_title else ""
            lines.append(f"[{i}{section}{page}] {cand.content}")
            citations.append((i, cand))
        return "\n\n".join(lines), citations

    async def _open_query_session(
        self,
        *,
        auth: AuthContext,
        query: str,
        collection_ids: list[UUID],
    ) -> UUID:
        new_id = uuid4()
        await self.session.execute(
            text(
                "INSERT INTO query_sessions "
                "(id, tenant_id, user_id, query_text, normalized_query, "
                " collection_ids, status) "
                "VALUES (:id, :tid, :uid, :q, :nq, "
                "        CAST(:cids AS uuid[]), 'running')"
            ),
            {
                "id": str(new_id),
                "tid": str(auth.tenant_id),
                "uid": str(auth.user_id),
                "q": query,
                "nq": " ".join(query.lower().split()),
                "cids": [str(c) for c in collection_ids],
            },
        )
        return new_id

    async def _persist_candidates(
        self,
        query_session_id: UUID,
        tenant_id: UUID,
        candidates: list[Candidate],
    ) -> None:
        if not candidates:
            return
        for cand in candidates:
            await self.session.execute(
                text(
                    "INSERT INTO retrieval_results "
                    "(tenant_id, query_session_id, chunk_id, retrieval_stage, "
                    " rank, score, metadata) "
                    "VALUES (:tid, :qs, :cid, :stage, :rank, :score, "
                    "        CAST(:meta AS jsonb))"
                ),
                {
                    "tid": str(tenant_id),
                    "qs": str(query_session_id),
                    "cid": str(cand.chunk_id),
                    "stage": cand.stage.value,
                    "rank": cand.rank,
                    "score": cand.score,
                    "meta": _json_dumps(cand.metadata),
                },
            )

    async def _persist_generated_answer(
        self,
        *,
        query_session_id: UUID,
        tenant_id: UUID,
        answer_text: str,
        model_provider: str,
        model_name: str,
        prompt_version_id: UUID | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        grounding_score: float | None,
    ) -> UUID:
        new_id = uuid4()
        await self.session.execute(
            text(
                "INSERT INTO generated_answers "
                "(id, tenant_id, query_session_id, answer_text, model_provider, "
                " model_name, prompt_version_id, input_tokens, output_tokens, "
                " cost_usd, grounding_score) "
                "VALUES (:id, :tid, :qs, :ans, :prov, :model, :pv, "
                "        :it, :ot, :cost, :ground)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "qs": str(query_session_id),
                "ans": answer_text,
                "prov": model_provider,
                "model": model_name,
                "pv": str(prompt_version_id) if prompt_version_id else None,
                "it": input_tokens,
                "ot": output_tokens,
                "cost": cost_usd,
                "ground": grounding_score,
            },
        )
        return new_id

    async def _persist_citations(
        self,
        *,
        generated_answer_id: UUID,
        tenant_id: UUID,
        citations: list[tuple[int, Candidate]],
        answer_text: str,
    ) -> list[CitationOut]:
        # Filter to citations actually referenced in the answer (e.g. "[3]").
        referenced_indices = set(_referenced_indices(answer_text))
        out: list[CitationOut] = []
        for idx, cand in citations:
            if referenced_indices and idx not in referenced_indices:
                continue
            citation_id = uuid4()
            await self.session.execute(
                text(
                    "INSERT INTO answer_citations "
                    "(id, tenant_id, generated_answer_id, chunk_id, "
                    " citation_index, quoted_text, relevance_score) "
                    "VALUES (:id, :tid, :ga, :cid, :idx, :qt, :score)"
                ),
                {
                    "id": str(citation_id),
                    "tid": str(tenant_id),
                    "ga": str(generated_answer_id),
                    "cid": str(cand.chunk_id),
                    "idx": idx,
                    "qt": cand.content[:500],
                    "score": cand.score,
                },
            )
            out.append(
                CitationOut(
                    citation_id=citation_id,
                    chunk_id=cand.chunk_id,
                    document_id=cand.document_id,
                    citation_index=idx,
                    quoted_text=cand.content[:500],
                    page_number=cand.page_number,
                    section_title=cand.section_title,
                    relevance_score=cand.score,
                )
            )
        return out

    async def _persist_usage(
        self,
        *,
        query_session_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        usage_type: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        total_cost_usd: Decimal,
    ) -> None:
        await self.session.execute(
            text(
                "INSERT INTO usage_records "
                "(tenant_id, user_id, query_session_id, usage_type, provider, "
                " model_name, input_tokens, output_tokens, total_cost_usd) "
                "VALUES (:tid, :uid, :qs, :ut, :prov, :model, "
                "        :it, :ot, :cost)"
            ),
            {
                "tid": str(tenant_id),
                "uid": str(user_id),
                "qs": str(query_session_id),
                "ut": usage_type,
                "prov": provider,
                "model": model_name,
                "it": input_tokens,
                "ot": output_tokens,
                "cost": total_cost_usd,
            },
        )

    async def _close_query_session(
        self,
        *,
        query_session_id: UUID,
        status: str,
        latency_ms: int,
        total_cost_usd: float,
        error_message: str | None = None,
    ) -> None:
        await self.session.execute(
            text(
                "UPDATE query_sessions "
                "SET status=:status, latency_ms=:lat, total_cost_usd=:cost "
                "WHERE id=:id"
            ),
            {
                "id": str(query_session_id),
                "status": status,
                "lat": latency_ms,
                "cost": total_cost_usd,
            },
        )
        # The schema doesn't have an error_message column on query_sessions;
        # we encode it into normalized_query as a fallback for v1. Phase 6
        # (observability) adds proper failure capture via OpenTelemetry events.
        if error_message:
            await self.session.execute(
                text(
                    "UPDATE query_sessions "
                    "SET normalized_query = COALESCE(normalized_query, '') || "
                    "    ' [error: ' || :err || ']' "
                    "WHERE id=:id"
                ),
                {"id": str(query_session_id), "err": error_message[:200]},
            )


# ---- Pure helpers ----

_CITATION_REF_RE = re.compile(r"\[(\d+)\]")
_MIN_TOKEN_LEN = 3  # ignore single chars and short stop-words for grounding
# Conservative chars-per-token used for the budget estimate. Real tokenization
# requires the model's tokenizer; we under-estimate intentionally so soft caps
# trigger before the actual call.
_CHARS_PER_TOKEN = 4


def _approx_token_count(text_blob: str) -> int:
    """Cheap character-based proxy for prompt token count.

    Real tokenization (tiktoken / model-specific) is overkill for a
    budget-gate over-cap. We round up so the estimate biases toward
    deny-then-allow rather than allow-then-overspend.
    """
    if not text_blob:
        return 0
    return max(1, (len(text_blob) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def _referenced_indices(answer_text: str) -> list[int]:
    return [int(m) for m in _CITATION_REF_RE.findall(answer_text)]


def _token_overlap_score(answer: str, context: str) -> float | None:
    """Cheap grounding signal: fraction of answer tokens present in context.

    Returns None for empty answers. Bigrams would be a stronger signal but
    we keep it cheap; Phase 4's layered hallucination detector replaces this.
    """
    if not answer.strip():
        return None
    answer_tokens = {t.lower() for t in re.findall(r"\w+", answer) if len(t) >= _MIN_TOKEN_LEN}
    if not answer_tokens:
        return None
    context_tokens = {t.lower() for t in re.findall(r"\w+", context) if len(t) >= _MIN_TOKEN_LEN}
    if not context_tokens:
        return 0.0
    return round(len(answer_tokens & context_tokens) / len(answer_tokens), 4)


def _json_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)
