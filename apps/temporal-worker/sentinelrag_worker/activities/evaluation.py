"""Evaluation activities — list cases, score one case, finalize run.

Each activity opens its own DB session and binds tenant context.

The ``score_case`` activity is the workhorse: it runs the configured query
through the orchestrator, then runs each evaluator against the produced
answer + retrieved context, then writes a single ``evaluation_scores`` row.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from sentinelrag_shared.evaluation import (
    AnswerCorrectnessEvaluator,
    CitationAccuracyEvaluator,
    ContextRelevanceEvaluator,
    EvalCase,
    EvalContext,
    Evaluator,
    FaithfulnessEvaluator,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from temporalio import activity

# DB engine cache (separate from ingestion's because process isolation is
# nice but not strictly required).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _get_session_factory() -> async_sessionmaker:
    global _engine, _session_factory  # noqa: PLW0603
    if _session_factory is None:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag",
        )
        _engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=5)
        _session_factory = async_sessionmaker(
            bind=_engine, expire_on_commit=False, autoflush=False
        )
    return _session_factory


@asynccontextmanager
async def _session_for_tenant(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield session


def _as_uuid(v: str | UUID) -> UUID:
    return v if isinstance(v, UUID) else UUID(v)


_ALL_EVALUATORS: list[Evaluator] = [
    ContextRelevanceEvaluator(),
    FaithfulnessEvaluator(),
    AnswerCorrectnessEvaluator(),
    CitationAccuracyEvaluator(),
]


@activity.defn
async def mark_run_running(run_id: str, tenant_id: str) -> None:
    async with _session_for_tenant(_as_uuid(tenant_id)) as session:
        await session.execute(
            text(
                "UPDATE evaluation_runs SET status='running', started_at=now() "
                "WHERE id=:id"
            ),
            {"id": str(_as_uuid(run_id))},
        )


@activity.defn
async def list_case_ids(dataset_id: str, tenant_id: str) -> list[str]:
    async with _session_for_tenant(_as_uuid(tenant_id)) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM evaluation_cases "
                    "WHERE dataset_id=:did ORDER BY created_at"
                ),
                {"did": str(_as_uuid(dataset_id))},
            )
        ).fetchall()
    return [str(r[0]) for r in rows]


@activity.defn
async def score_case(
    run_id: str,
    case_id: str,
    tenant_id: str,
    collection_ids: list[str],
    prompt_version_id: str | None,
    model_config: dict[str, Any],
    retrieval_config: dict[str, Any],
) -> dict[str, Any]:
    """Run a single eval case end-to-end and persist the score row.

    This activity is the natural place to import the API service's
    RagOrchestrator. We import lazily to avoid loading FastAPI at module
    init in the worker.
    """
    # Lazy import — keeps the worker startup light.
    from app.services.rag_orchestrator import (  # noqa: PLC0415
        GenerationConfig,
        QueryOptions,
        RagOrchestrator,
        RetrievalConfig,
    )
    from sentinelrag_shared.auth import AuthContext  # noqa: PLC0415

    tid = _as_uuid(tenant_id)
    cid = _as_uuid(case_id)
    rid = _as_uuid(run_id)

    async with _session_for_tenant(tid) as session:
        # Fetch the case.
        case_row = (
            await session.execute(
                text(
                    "SELECT input_query, expected_answer, "
                    "       expected_citation_chunk_ids, grading_rubric "
                    "FROM evaluation_cases WHERE id=:id"
                ),
                {"id": str(cid)},
            )
        ).fetchone()
        if case_row is None:
            return {"skipped": True, "reason": "case-not-found"}

        # Use a system-level "evaluation" auth context. Per ADR-0008 the
        # eval framework runs with platform-level permissions. We grant
        # the run's tenant + a synthetic user ID for audit purposes.
        eval_user_id = uuid4()
        # Ensure a user row exists for the FK on query_sessions; we create
        # an ephemeral evaluator user with email scoped to the run.
        await session.execute(
            text(
                "INSERT INTO users (id, tenant_id, email) "
                "VALUES (:uid, :tid, :email) "
                "ON CONFLICT (tenant_id, email) DO NOTHING"
            ),
            {
                "uid": str(eval_user_id),
                "tid": str(tid),
                "email": f"evaluator+{rid}@sentinelrag.example.com",
            },
        )

        auth = AuthContext(
            user_id=eval_user_id,
            tenant_id=tid,
            email=f"evaluator+{rid}@sentinelrag.example.com",
            permissions=frozenset(
                {"queries:execute", "documents:read", "collections:read"}
            ),
        )

        orchestrator = RagOrchestrator(
            session=session,
            embedding_model=model_config.get(
                "embedding_model",
                os.environ.get(
                    "DEFAULT_EMBEDDING_MODEL", "ollama/nomic-embed-text"
                ),
            ),
            ollama_base_url=os.environ.get(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            ),
        )

        result = await orchestrator.run(
            query=str(case_row.input_query),
            auth=auth,
            collection_ids=[_as_uuid(c) for c in collection_ids],
            retrieval=RetrievalConfig(**{
                k: v
                for k, v in retrieval_config.items()
                if k in {"mode", "top_k_bm25", "top_k_vector", "top_k_hybrid",
                          "top_k_rerank", "ef_search"}
            }) if retrieval_config else RetrievalConfig(),
            generation=GenerationConfig(
                model=model_config.get("model", "ollama/llama3.1:8b"),
                temperature=model_config.get("temperature", 0.1),
                max_tokens=model_config.get("max_tokens", 800),
            ),
            options=QueryOptions(
                prompt_version_id=_as_uuid(prompt_version_id)
                if prompt_version_id
                else None,
            ),
        )

        # Build EvalCase + EvalContext.
        eval_case = EvalCase(
            case_id=cid,
            input_query=str(case_row.input_query),
            expected_answer=case_row.expected_answer,
            expected_citation_chunk_ids=[
                _as_uuid(x) for x in (case_row.expected_citation_chunk_ids or [])
            ],
            grading_rubric=case_row.grading_rubric or {},
        )

        # Pull the rerank-stage retrieval results to use as context.
        retrieved_rows = (
            await session.execute(
                text(
                    "SELECT rr.chunk_id, dc.content "
                    "FROM retrieval_results rr "
                    "JOIN document_chunks dc ON dc.id = rr.chunk_id "
                    "WHERE rr.query_session_id = :qs "
                    "  AND rr.retrieval_stage = 'rerank' "
                    "ORDER BY rr.rank"
                ),
                {"qs": str(result.query_session_id)},
            )
        ).fetchall()

        eval_context = EvalContext(
            answer_text=result.answer,
            retrieved_chunks=[
                {"chunk_id": str(r.chunk_id), "content": r.content}
                for r in retrieved_rows
            ],
            cited_chunk_ids=[c.chunk_id for c in result.citations],
            cited_quoted_texts=[c.quoted_text or "" for c in result.citations],
        )

        # Run all evaluators.
        scores: dict[str, float | None] = {}
        for evaluator in _ALL_EVALUATORS:
            output = await evaluator.evaluate(case=eval_case, context=eval_context)
            scores[evaluator.name] = output.score

        # Persist the evaluation_scores row.
        await session.execute(
            text(
                "INSERT INTO evaluation_scores "
                "(tenant_id, evaluation_run_id, evaluation_case_id, "
                " query_session_id, context_relevance_score, "
                " faithfulness_score, answer_correctness_score, "
                " citation_accuracy_score, latency_ms, cost_usd) "
                "VALUES (:tid, :rid, :cid, :qs, :ctx, :faith, :ans, :cite, "
                "        :lat, :cost)"
            ),
            {
                "tid": str(tid),
                "rid": str(rid),
                "cid": str(cid),
                "qs": str(result.query_session_id),
                "ctx": scores.get("context_relevance"),
                "faith": scores.get("faithfulness"),
                "ans": scores.get("answer_correctness"),
                "cite": scores.get("citation_accuracy"),
                "lat": result.latency_ms,
                "cost": result.cost_usd,
            },
        )

    return {
        "case_id": str(cid),
        "scores": scores,
        "latency_ms": result.latency_ms,
    }


@activity.defn
async def finalize_run(run_id: str, tenant_id: str, status: str = "completed") -> None:
    async with _session_for_tenant(_as_uuid(tenant_id)) as session:
        await session.execute(
            text(
                "UPDATE evaluation_runs "
                "SET status=:status, completed_at=now() WHERE id=:id"
            ),
            {"id": str(_as_uuid(run_id)), "status": status},
        )


ALL_ACTIVITIES = [mark_run_running, list_case_ids, score_case, finalize_run]
