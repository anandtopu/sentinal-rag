"""Regression tests for evaluation orchestration gaps."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.main import create_app
from app.schemas.evaluations import EvaluationCaseCreate, EvaluationRunCreate
from app.services.rag_orchestrator import RagOrchestrator
from sentinelrag_shared.contracts import (
    EvaluationRunWorkflowInput,
    EvaluationRunWorkflowResult,
)
from sentinelrag_shared.retrieval import Candidate, RetrievalStage
from sentinelrag_worker.activities.evaluation import _build_reranker


def _candidate(rank: int = 1) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="kubernetes rollback uses helm",
        score=0.5,
        rank=rank,
        stage=RetrievalStage.HYBRID_MERGE,
        metadata={"source": "test"},
    )


@pytest.mark.unit
def test_eval_workflow_contract_tracks_actor_and_failures() -> None:
    payload = EvaluationRunWorkflowInput.model_validate(
        {
            "evaluation_run_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "dataset_id": str(uuid4()),
            "actor_user_id": str(uuid4()),
            "collection_ids": [str(uuid4())],
        }
    )

    result = EvaluationRunWorkflowResult(
        evaluation_run_id=payload.evaluation_run_id,
        cases_completed=1,
        cases_failed=2,
    )

    assert payload.actor_user_id is not None
    assert result.model_dump(mode="json")["cases_failed"] == 2


@pytest.mark.unit
def test_top_k_rerank_zero_disables_rerank_without_dropping_context() -> None:
    orchestrator = RagOrchestrator(
        session=object(),  # type: ignore[arg-type]
        embedding_model="ollama/nomic-embed-text",
        ollama_base_url="http://localhost:11434",
    )
    candidates = [_candidate(1), _candidate(2)]

    reranked = orchestrator._rerank(query="rollback", merged=candidates, top_k=0)

    assert [c.chunk_id for c in reranked] == [c.chunk_id for c in candidates]
    assert all(c.stage is RetrievalStage.RERANK for c in reranked)
    assert all(c.metadata["rerank_disabled"] is True for c in reranked)


@pytest.mark.unit
def test_worker_uses_noop_reranker_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_RERANKER", raising=False)

    reranker = _build_reranker()

    assert reranker.model_name == "noop"


@pytest.mark.unit
def test_eval_runs_list_route_is_registered() -> None:
    app = create_app()
    methods_by_path = {
        route.path: getattr(route, "methods", set())
        for route in app.routes
        if route.path in {"/api/v1/eval/runs", "/api/v1/eval/datasets"}
    }

    assert "GET" in methods_by_path["/api/v1/eval/runs"]
    assert "GET" in methods_by_path["/api/v1/eval/datasets"]


@pytest.mark.unit
def test_eval_run_schema_rejects_unknown_retrieval_keys() -> None:
    with pytest.raises(ValueError, match="Unknown retrieval_config keys"):
        EvaluationRunCreate(
            dataset_id=uuid4(),
            name="run",
            collection_ids=[uuid4()],
            retrieval_config={"surprise": True},
            model_config={},
        )


@pytest.mark.unit
def test_eval_case_schema_validates_rubric_shape() -> None:
    with pytest.raises(ValueError, match="must_include"):
        EvaluationCaseCreate(
            input_query="rollback",
            grading_rubric={"must_include": "helm"},
        )
