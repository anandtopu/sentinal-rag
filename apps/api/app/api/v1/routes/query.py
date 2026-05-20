"""/query and /query/{id}/trace routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sentinelrag_shared.audit import (
    DualWriteAuditService,
    ObjectStorageAuditSink,
    PostgresAuditSink,
)
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors.exceptions import NotFoundError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies import (
    AuditStorageDep,
    BudgetReservationDep,
    EmbedderDep,
    IdempotencyDep,
    RerankerDep,
    RetrievalClientDep,
)
from app.schemas.common import Page
from app.schemas.query import (
    CitationRead,
    GeneratedAnswerSummary,
    QueryRequest,
    QueryResponse,
    QuerySessionListItem,
    QueryTraceResponse,
    QueryUsage,
    RetrievalResultRead,
)
from app.services.idempotency import IdempotencyService
from app.services.query_history_service import QueryHistoryService
from app.services.rag import (
    GenerationConfig,
    Orchestrator,
    QueryOptions,
    QueryResult,
    RetrievalConfig,
)

router = APIRouter(prefix="/query", tags=["query"])

# Status values that mean the orchestrator has stopped writing to this row.
_TERMINAL_STATUSES = frozenset({"completed", "abstained", "failed"})

# SSE poll interval and ceiling. The orchestrator typically completes in 1-10s;
# 60 ticks @ 1s = 1 minute hard cap on a single SSE connection.
_SSE_POLL_INTERVAL_S = 1.0
_SSE_MAX_TICKS = 60


def requires_cloud_model_permission(model: str) -> bool:
    """Return True when the model alias routes to a paid cloud provider."""
    return not model.startswith("ollama/")


@router.post("", response_model=QueryResponse)
async def execute_query(
    payload: QueryRequest,
    ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    reranker: RerankerDep,
    audit_storage: AuditStorageDep,
    idempotency: IdempotencyDep,
    budget_reservations: BudgetReservationDep,
    retrieval_client: RetrievalClientDep,
    embedder: EmbedderDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> QueryResponse:
    settings = get_settings()
    requested_model = payload.generation.model or settings.default_generation_model
    if requires_cloud_model_permission(requested_model):
        ctx.require_permission("llm:cloud_models")

    # R3.S2: namespace by tenant + hash the body so a malicious client
    # can't reuse a key with a different payload and get the cached
    # response of the old payload.
    cache_key: str | None = None
    if idempotency_key:
        body_hash = IdempotencyService.body_hash(
            payload.model_dump_json().encode("utf-8")
        )
        cache_key = IdempotencyService.cache_key(
            tenant_id=ctx.tenant_id,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
        )
        cached = await _resolve_idempotent_response(idempotency, cache_key)
        if cached is not None:
            return cached
        claimed = await idempotency.try_claim(cache_key)
        if not claimed:
            # Couldn't claim — race with a leader that finished between
            # our get and our claim. Read once more before giving up.
            cached = await _resolve_idempotent_response(idempotency, cache_key)
            if cached is not None:
                return cached

    orchestrator = Orchestrator(
        session=db,
        embedding_model=settings.default_embedding_model,
        ollama_base_url=settings.ollama_base_url,
        reranker=reranker,
        audit_service=DualWriteAuditService(
            primary=PostgresAuditSink(db),
            secondaries=[ObjectStorageAuditSink(audit_storage)],
        ),
        generation_timeout_seconds=settings.generation_timeout_seconds,
        budget_reservations=budget_reservations,
        retrieval_client=retrieval_client,
        embedder=embedder,
    )
    try:
        result = await orchestrator.run(
            query=payload.query,
            auth=ctx,
            collection_ids=list(payload.collection_ids),
            retrieval=RetrievalConfig(
                mode=payload.retrieval.mode,
                top_k_bm25=payload.retrieval.top_k_bm25,
                top_k_vector=payload.retrieval.top_k_vector,
                top_k_hybrid=payload.retrieval.top_k_hybrid,
                top_k_rerank=payload.retrieval.top_k_rerank,
                ef_search=payload.retrieval.ef_search,
            ),
            generation=GenerationConfig(
                model=requested_model,
                temperature=payload.generation.temperature,
                max_tokens=payload.generation.max_tokens,
            ),
            options=QueryOptions(
                include_debug_trace=payload.options.include_debug_trace,
                abstain_if_unsupported=payload.options.abstain_if_unsupported,
            ),
        )
    except Exception:
        # R3.S2: orchestrator failure → free the pending claim so a
        # retry isn't forced to wait the full pending TTL.
        if cache_key is not None:
            await idempotency.release_claim(cache_key)
        raise

    response = _to_query_response(
        result,
        include_citations=payload.options.include_citations,
    )
    if cache_key is not None:
        await idempotency.store_result(cache_key, response.model_dump_json())
    return response


async def _resolve_idempotent_response(
    idempotency: IdempotencyService, cache_key: str
) -> QueryResponse | None:
    """Return the cached response (if any), waiting briefly for a pending leader."""
    cached = await idempotency.get_cached(cache_key)
    if cached is None:
        return None
    if "__pending__" in cached:
        cached = await idempotency.wait_for_result(cache_key)
        if cached is None or "__pending__" in cached:
            return None
    return QueryResponse.model_validate(cached)


def _to_query_response(
    result: QueryResult, *, include_citations: bool = True
) -> QueryResponse:
    citations: list[CitationRead] = []
    if include_citations:
        citations = [
            CitationRead(
                citation_id=c.citation_id,
                document_id=c.document_id,
                chunk_id=c.chunk_id,
                citation_index=c.citation_index,
                page_number=c.page_number,
                section_title=c.section_title,
                quoted_text=c.quoted_text,
                relevance_score=c.relevance_score,
            )
            for c in result.citations
        ]

    return QueryResponse(
        query_session_id=result.query_session_id,
        answer=result.answer,
        confidence_score=result.confidence_score,
        grounding_score=result.grounding_score,
        hallucination_risk_score=result.hallucination_risk_score,
        nli_verdict=result.nli_verdict,
        judge_verdict=result.judge_verdict,
        citations=citations,
        usage=QueryUsage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        ),
    )


async def _build_trace(
    db: AsyncSession, query_session_id: UUID
) -> QueryTraceResponse | None:
    """Read the full trace for a session in one round-trip set.

    Returns ``None`` when the session row doesn't exist (yet) — used by the
    SSE stream to detect "not-yet-persisted" without raising.
    """
    session_row = (
        await db.execute(
            text(
                "SELECT id, query_text, status, latency_ms, created_at "
                "FROM query_sessions WHERE id = :id"
            ),
            {"id": str(query_session_id)},
        )
    ).fetchone()
    if session_row is None:
        return None

    retrieval_rows = (
        await db.execute(
            text(
                "SELECT chunk_id, retrieval_stage, rank, score, metadata "
                "FROM retrieval_results WHERE query_session_id = :id "
                "ORDER BY retrieval_stage, rank"
            ),
            {"id": str(query_session_id)},
        )
    ).fetchall()

    gen_row = (
        await db.execute(
            text(
                "SELECT model_name, prompt_version_id, input_tokens, output_tokens, "
                "       cost_usd, grounding_score, hallucination_risk_score, "
                "       confidence_score, nli_verdict, judge_verdict "
                "FROM generated_answers WHERE query_session_id = :id"
            ),
            {"id": str(query_session_id)},
        )
    ).fetchone()

    return QueryTraceResponse(
        query_session_id=session_row.id,
        query=session_row.query_text,
        status=session_row.status,
        latency_ms=session_row.latency_ms,
        created_at=session_row.created_at,
        retrieval_results=[
            RetrievalResultRead(
                chunk_id=r.chunk_id,
                stage=r.retrieval_stage,
                rank=r.rank,
                score=float(r.score),
                metadata=_coerce_metadata(r.metadata),
            )
            for r in retrieval_rows
        ],
        generation=(
            GeneratedAnswerSummary(
                model=gen_row.model_name,
                prompt_version_id=gen_row.prompt_version_id,
                input_tokens=gen_row.input_tokens,
                output_tokens=gen_row.output_tokens,
                cost_usd=float(gen_row.cost_usd) if gen_row.cost_usd is not None else None,
                grounding_score=gen_row.grounding_score,
                hallucination_risk_score=gen_row.hallucination_risk_score,
                confidence_score=gen_row.confidence_score,
                nli_verdict=gen_row.nli_verdict,
                judge_verdict=gen_row.judge_verdict,
            )
            if gen_row is not None
            else None
        ),
    )


def _coerce_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.get("", response_model=Page[QuerySessionListItem])
async def list_query_sessions(
    _ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[QuerySessionListItem]:
    """Recent query sessions (newest first), tenant-scoped via RLS. Powers the
    dashboard "Recent queries" feed (BACKLOG B10 #3)."""
    items = await QueryHistoryService(db).list_recent(limit=limit, offset=offset)
    return Page[QuerySessionListItem](
        items=items, total=len(items), limit=limit, offset=offset
    )


@router.get("/{query_session_id}/trace", response_model=QueryTraceResponse)
async def read_trace(
    query_session_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueryTraceResponse:
    trace = await _build_trace(db, query_session_id)
    if trace is None:
        raise NotFoundError("Query session not found.")
    return trace


@router.get("/{query_session_id}/trace/stream")
async def stream_trace(
    query_session_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Server-Sent Events stream of the trace until status reaches a terminal state.

    Emits ``event: trace`` frames with the same JSON body as ``GET .../trace``,
    then a final ``event: done`` (or ``event: error``) when the orchestrator
    finishes. Falls under the ``queries:execute`` permission like the GET.

    The frontend ``/query-playground`` page subscribes to this in place of
    polling. The client should still gracefully fall back to polling if the
    EventSource fails (e.g. behind a proxy that buffers SSE).
    """

    async def event_gen() -> AsyncIterator[bytes]:
        for _tick in range(_SSE_MAX_TICKS):
            trace = await _build_trace(db, query_session_id)
            if trace is None:
                # The session row may not have committed yet if the producer
                # is still inside its transaction. Emit a keepalive comment
                # and keep waiting.
                yield b": waiting-for-session\n\n"
                await asyncio.sleep(_SSE_POLL_INTERVAL_S)
                continue

            payload = trace.model_dump(mode="json")
            yield f"event: trace\ndata: {json.dumps(payload)}\n\n".encode()

            if trace.status in _TERMINAL_STATUSES:
                yield b"event: done\ndata: {}\n\n"
                return

            await asyncio.sleep(_SSE_POLL_INTERVAL_S)

        # Hit the cap without a terminal status — tell the client to fall back.
        yield b'event: timeout\ndata: {"reason":"max-ticks-exceeded"}\n\n'

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
        },
    )
