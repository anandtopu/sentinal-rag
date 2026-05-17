"""Stage-level unit tests for ``apps.api.app.services.rag`` (R1.S1).

End-to-end orchestrator behaviour is covered by the existing regression
tests in ``test_query_response_options.py`` and the integration suite.
These tests target the per-stage seams + helpers in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.services.rag._helpers import (
    approx_token_count,
    json_dumps,
    referenced_indices,
    restage_candidates,
    token_overlap_score,
)
from app.services.rag.stages.context_assembly import ContextAssemblyStage
from app.services.rag.stages.grounding import GroundingStage
from app.services.rag.types import (
    GenerationConfig,
    QueryContext,
    QueryOptions,
    RetrievalConfig,
)
from sentinelrag_shared.retrieval import Candidate, RetrievalStage


def _candidate(idx: int, *, content: str | None = None) -> Candidate:
    return Candidate(
        chunk_id=UUID(int=idx),
        document_id=UUID(int=100 + idx),
        content=content or f"chunk {idx} content",
        score=1.0 - 0.1 * idx,
        rank=idx,
        stage=RetrievalStage.HYBRID_MERGE,
        page_number=idx,
        section_title=f"section {idx}",
        metadata={"orig": idx},
    )


@dataclass
class _FakeAuth:
    tenant_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)


def _ctx(reranked: list[Candidate] | None = None, *, answer: str = "") -> QueryContext:
    ctx = QueryContext(
        query="rollback",
        auth=_FakeAuth(),  # type: ignore[arg-type]
        collection_ids=[],
        retrieval_cfg=RetrievalConfig(),
        generation_cfg=GenerationConfig(),
        options=QueryOptions(),
        embedder=None,  # type: ignore[arg-type]
        ollama_base_url="http://localhost:11434",
    )
    if reranked is not None:
        ctx.reranked = reranked
    if answer:
        ctx.answer_text = answer
    return ctx


# ---------- helpers ----------


@pytest.mark.unit
def test_approx_token_count_rounds_up() -> None:
    # 4 chars/token, ceiling division → 4 chars = 1 token, 5 chars = 2 tokens
    assert approx_token_count("") == 0
    assert approx_token_count("abcd") == 1
    assert approx_token_count("abcde") == 2


@pytest.mark.unit
def test_referenced_indices_extracts_citation_markers() -> None:
    assert referenced_indices("see [1] and [3]") == [1, 3]
    assert referenced_indices("nothing here") == []


@pytest.mark.unit
def test_token_overlap_score_handles_edge_cases() -> None:
    assert token_overlap_score("", "context") is None
    # Two-word answer, both present in context.
    assert token_overlap_score("hello world", "hello world abc") == 1.0
    # No overlap on long-enough tokens.
    assert token_overlap_score("alpha", "beta gamma") == 0.0


@pytest.mark.unit
def test_restage_candidates_renumbers_rank_and_changes_stage() -> None:
    original = [_candidate(1), _candidate(2)]
    out = restage_candidates(original, RetrievalStage.HYBRID_MERGE)
    assert [c.rank for c in out] == [1, 2]
    assert all(c.stage is RetrievalStage.HYBRID_MERGE for c in out)
    # Original candidates unchanged (function returns new instances).
    assert original[0].rank == 1
    assert original[0].stage is RetrievalStage.HYBRID_MERGE


@pytest.mark.unit
def test_json_dumps_handles_uuid() -> None:
    payload: dict[str, Any] = {"id": uuid4()}
    out = json_dumps(payload)
    assert isinstance(out, str)
    assert "id" in out


# ---------- ContextAssemblyStage ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_context_assembly_numbers_citations_and_renders_section_page() -> None:
    ctx = _ctx(reranked=[_candidate(1), _candidate(2)])
    await ContextAssemblyStage().run(ctx)
    # Two citations, indexed 1 and 2.
    assert [idx for idx, _ in ctx.citations_for_persist] == [1, 2]
    assert "[1 — section 1, page 1]" in ctx.context_text
    assert "[2 — section 2, page 2]" in ctx.context_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_context_assembly_empty_reranked_yields_empty_outputs() -> None:
    ctx = _ctx(reranked=[])
    await ContextAssemblyStage().run(ctx)
    assert ctx.context_text == ""
    assert ctx.citations_for_persist == []


# ---------- GroundingStage ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grounding_stage_sets_token_overlap_score() -> None:
    ctx = _ctx(answer="rollback procedure ready")
    ctx.context_text = "rollback procedure documented"
    await GroundingStage().run(ctx)
    # 'rollback' + 'procedure' overlap; 'ready' doesn't. 2/3 ≈ 0.6667
    assert ctx.grounding_score == pytest.approx(0.6667, abs=0.001)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grounding_stage_returns_none_for_empty_answer() -> None:
    ctx = _ctx(answer="")
    ctx.context_text = "anything"
    await GroundingStage().run(ctx)
    assert ctx.grounding_score is None


# ---------- QueryContext.to_query_result ----------


@pytest.mark.unit
def test_to_query_result_requires_query_session_id() -> None:
    ctx = _ctx()
    with pytest.raises(RuntimeError, match="query_session_id"):
        ctx.to_query_result()


@pytest.mark.unit
def test_to_query_result_packs_costs_and_citations() -> None:
    ctx = _ctx()
    ctx.query_session_id = uuid4()
    ctx.answer_text = "ok"
    ctx.gen_cost = Decimal("0.0042")
    ctx.input_tokens = 17
    ctx.output_tokens = 5
    ctx.grounding_score = 0.5
    ctx.latency_ms = 123
    result = ctx.to_query_result()
    assert result.answer == "ok"
    assert result.cost_usd == pytest.approx(0.0042)
    assert result.input_tokens == 17
    assert result.output_tokens == 5
    assert result.latency_ms == 123
    assert result.grounding_score == 0.5
    assert result.citations == []
