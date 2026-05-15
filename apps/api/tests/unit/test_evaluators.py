"""Unit tests for the four custom evaluators."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sentinelrag_shared.evaluation import (
    AnswerCorrectnessEvaluator,
    CitationAccuracyEvaluator,
    ContextRelevanceEvaluator,
    EvalCase,
    EvalContext,
    FaithfulnessEvaluator,
)


def _case(**kwargs) -> EvalCase:
    defaults = {
        "case_id": uuid4(),
        "input_query": "test query",
    }
    defaults.update(kwargs)
    return EvalCase(**defaults)


def _ctx(
    *,
    answer: str = "",
    chunks: list[str] | None = None,
    cited_chunk_ids: list[UUID] | None = None,
    retrieved_chunk_ids: list[UUID] | None = None,
) -> EvalContext:
    chunk_ids = retrieved_chunk_ids or [uuid4() for _ in (chunks or [])]
    return EvalContext(
        answer_text=answer,
        retrieved_chunks=[
            {"chunk_id": str(chunk_id), "content": c}
            for chunk_id, c in zip(chunk_ids, chunks or [], strict=True)
        ],
        cited_chunk_ids=cited_chunk_ids or [],
        cited_quoted_texts=[],
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestCitationAccuracy:
    async def test_returns_none_when_no_expected_citations(self) -> None:
        case = _case()
        ctx = _ctx(cited_chunk_ids=[uuid4()])
        out = await CitationAccuracyEvaluator().evaluate(case=case, context=ctx)
        assert out.score is None

    async def test_full_overlap_scores_1(self) -> None:
        chunk_id = uuid4()
        case = _case(expected_citation_chunk_ids=[chunk_id])
        ctx = _ctx(
            chunks=["kubernetes rollback"],
            cited_chunk_ids=[chunk_id],
            retrieved_chunk_ids=[chunk_id],
        )
        out = await CitationAccuracyEvaluator().evaluate(case=case, context=ctx)
        assert out.score == 1.0

    async def test_partial_overlap_scores_proportionally(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        case = _case(expected_citation_chunk_ids=[a, b, c])
        ctx = _ctx(
            chunks=["a", "b", "c"],
            cited_chunk_ids=[a, b],
            retrieved_chunk_ids=[a, b, c],
        )  # 2 of 3 expected, no extras
        out = await CitationAccuracyEvaluator().evaluate(case=case, context=ctx)
        assert out.score is not None
        assert abs(out.score - ((2 / 3 + 1.0) / 2)) < 0.001

    async def test_extra_or_unretrieved_citations_reduce_precision(self) -> None:
        expected = uuid4()
        extra = uuid4()
        case = _case(expected_citation_chunk_ids=[expected])
        ctx = _ctx(
            chunks=["expected support"],
            cited_chunk_ids=[expected, extra],
            retrieved_chunk_ids=[expected],
        )

        out = await CitationAccuracyEvaluator().evaluate(case=case, context=ctx)

        assert out.score == 0.75


@pytest.mark.unit
@pytest.mark.asyncio
class TestAnswerCorrectness:
    async def test_returns_none_when_no_expected_or_rubric(self) -> None:
        case = _case()
        ctx = _ctx(answer="Some answer")
        out = await AnswerCorrectnessEvaluator().evaluate(case=case, context=ctx)
        assert out.score is None

    async def test_must_include_full_match(self) -> None:
        case = _case(grading_rubric={"must_include": ["kubernetes", "rollback"]})
        ctx = _ctx(answer="To rollback kubernetes deployments use helm rollback")
        out = await AnswerCorrectnessEvaluator().evaluate(case=case, context=ctx)
        assert out.score == 1.0

    async def test_must_not_include_violation(self) -> None:
        case = _case(
            grading_rubric={
                "must_include": ["helm"],
                "must_not_include": ["delete production"],
            }
        )
        ctx = _ctx(answer="Use helm to delete production namespace immediately")
        out = await AnswerCorrectnessEvaluator().evaluate(case=case, context=ctx)
        # must_include hits 1/1 = 1.0; must_not_include violation = 0.0
        # average = 0.5
        assert out.score == 0.5


@pytest.mark.unit
@pytest.mark.asyncio
class TestContextRelevance:
    async def test_no_chunks_scores_0(self) -> None:
        out = await ContextRelevanceEvaluator().evaluate(
            case=_case(input_query="kubernetes deployments"),
            context=_ctx(),
        )
        assert out.score == 0.0

    async def test_relevant_chunks_score_higher(self) -> None:
        on_topic = await ContextRelevanceEvaluator().evaluate(
            case=_case(input_query="kubernetes rollback procedure"),
            context=_ctx(chunks=["kubernetes rollback uses helm rollback command"]),
        )
        off_topic = await ContextRelevanceEvaluator().evaluate(
            case=_case(input_query="kubernetes rollback procedure"),
            context=_ctx(chunks=["the cat sat on the mat under the table"]),
        )
        assert on_topic.score is not None
        assert off_topic.score is not None
        assert on_topic.score > off_topic.score


@pytest.mark.unit
@pytest.mark.asyncio
class TestFaithfulness:
    async def test_empty_answer_returns_none(self) -> None:
        out = await FaithfulnessEvaluator().evaluate(
            case=_case(),
            context=_ctx(answer="", chunks=["something"]),
        )
        assert out.score is None

    async def test_answer_in_context_scores_high(self) -> None:
        out = await FaithfulnessEvaluator().evaluate(
            case=_case(),
            context=_ctx(
                answer="kubernetes rollback uses helm",
                chunks=[
                    "the proper kubernetes rollback procedure uses helm rollback "
                    "with the appropriate revision number"
                ],
            ),
        )
        assert out.score is not None
        assert out.score > 0.5

    async def test_answer_unsupported_scores_low(self) -> None:
        out = await FaithfulnessEvaluator().evaluate(
            case=_case(),
            context=_ctx(
                answer="quantum entanglement chemistry photons spectroscopy",
                chunks=["kubernetes deployment rollback procedure"],
            ),
        )
        assert out.score is not None
        assert out.score < 0.3
