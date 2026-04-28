"""Custom evaluators — token-overlap and rubric-driven, no LLM judge required.

These evaluators are deterministic, fast, and don't require a running LLM
provider. They're the baseline that ragas + LLM-as-judge variants (added
in Phase 6) compete against on the same data.
"""

from __future__ import annotations

import re
import time

from sentinelrag_shared.evaluation.base import (
    EvalCase,
    EvalContext,
    EvaluationOutput,
)

_WORD_RE = re.compile(r"\w+")
_MIN_TOKEN_LEN = 3  # ignore single chars and short stop-words like "is"/"of"


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text) if len(t) >= _MIN_TOKEN_LEN}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class CitationAccuracyEvaluator:
    """Fraction of expected_citation_chunk_ids actually cited.

    If no expected citations were provided, returns ``None`` (signaling that
    this metric isn't applicable to this case rather than a 0 score).
    """

    name = "citation_accuracy"

    async def evaluate(
        self, *, case: EvalCase, context: EvalContext
    ) -> EvaluationOutput:
        start = time.perf_counter()
        if not case.expected_citation_chunk_ids:
            return EvaluationOutput(
                name=self.name,
                score=None,
                reasoning="No expected citations specified.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        expected = set(case.expected_citation_chunk_ids)
        cited = set(context.cited_chunk_ids)
        score = len(expected & cited) / len(expected) if expected else 0.0
        latency_ms = int((time.perf_counter() - start) * 1000)
        return EvaluationOutput(
            name=self.name,
            score=round(score, 4),
            reasoning=(
                f"Cited {len(expected & cited)} of {len(expected)} expected "
                f"chunks; {len(cited - expected)} extra citations."
            ),
            latency_ms=latency_ms,
            extras={"expected_count": len(expected), "actual_count": len(cited)},
        )


class AnswerCorrectnessEvaluator:
    """Token-overlap of answer with expected_answer + rubric must_include / must_not_include.

    Returns ``None`` when neither expected_answer nor rubric is set.
    """

    name = "answer_correctness"

    async def evaluate(
        self, *, case: EvalCase, context: EvalContext
    ) -> EvaluationOutput:
        start = time.perf_counter()
        rubric = case.grading_rubric or {}
        must_include = [s.lower() for s in rubric.get("must_include", [])]
        must_not_include = [s.lower() for s in rubric.get("must_not_include", [])]

        if not case.expected_answer and not must_include and not must_not_include:
            return EvaluationOutput(
                name=self.name,
                score=None,
                reasoning="No expected_answer or rubric provided.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        answer_lower = context.answer_text.lower()
        component_scores: list[float] = []
        notes: list[str] = []

        if case.expected_answer:
            sim = _jaccard(_tokens(case.expected_answer), _tokens(context.answer_text))
            component_scores.append(sim)
            notes.append(f"jaccard={sim:.3f}")

        if must_include:
            hits = sum(1 for s in must_include if s in answer_lower)
            component_scores.append(hits / len(must_include))
            notes.append(f"must_include {hits}/{len(must_include)}")

        if must_not_include:
            violations = sum(1 for s in must_not_include if s in answer_lower)
            component_scores.append(1.0 - (violations / len(must_not_include)))
            if violations:
                notes.append(f"must_not_include violations: {violations}")

        score = sum(component_scores) / len(component_scores)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return EvaluationOutput(
            name=self.name,
            score=round(score, 4),
            reasoning="; ".join(notes),
            latency_ms=latency_ms,
        )


class ContextRelevanceEvaluator:
    """Token-overlap between query and retrieved chunks.

    Approximates ragas's ``context_relevance``. Higher score → the retrieved
    context is more on-topic. Doesn't penalize over-retrieval — that's the
    job of a separate context-precision metric (Phase 6).
    """

    name = "context_relevance"

    async def evaluate(
        self, *, case: EvalCase, context: EvalContext
    ) -> EvaluationOutput:
        start = time.perf_counter()
        if not context.retrieved_chunks:
            return EvaluationOutput(
                name=self.name,
                score=0.0,
                reasoning="No chunks retrieved.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        query_tokens = _tokens(case.input_query)
        if not query_tokens:
            return EvaluationOutput(
                name=self.name,
                score=None,
                reasoning="Query produced no scoreable tokens.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        per_chunk = []
        for chunk in context.retrieved_chunks:
            chunk_text = chunk.get("content", "")
            if not chunk_text:
                continue
            overlap = _jaccard(query_tokens, _tokens(chunk_text))
            per_chunk.append(overlap)

        if not per_chunk:
            return EvaluationOutput(
                name=self.name,
                score=0.0,
                reasoning="Retrieved chunks had no scoreable text.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        score = sum(per_chunk) / len(per_chunk)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return EvaluationOutput(
            name=self.name,
            score=round(score, 4),
            reasoning=f"Avg jaccard across {len(per_chunk)} chunks.",
            latency_ms=latency_ms,
        )


class FaithfulnessEvaluator:
    """Approximate faithfulness — fraction of answer tokens supported by context.

    Higher = more faithful. Mirrors ragas's ``faithfulness`` shape on cheap
    token statistics; the LLM-judge version (Phase 6) is more accurate but
    costs $.
    """

    name = "faithfulness"

    async def evaluate(
        self, *, case: EvalCase, context: EvalContext
    ) -> EvaluationOutput:
        start = time.perf_counter()
        del case
        if not context.answer_text.strip():
            return EvaluationOutput(
                name=self.name,
                score=None,
                reasoning="Empty answer.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        answer_tokens = _tokens(context.answer_text)
        if not answer_tokens:
            return EvaluationOutput(
                name=self.name,
                score=None,
                reasoning="Answer has no scoreable tokens.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        ctx_tokens: set[str] = set()
        for chunk in context.retrieved_chunks:
            ctx_tokens |= _tokens(chunk.get("content", ""))

        if not ctx_tokens:
            return EvaluationOutput(
                name=self.name,
                score=0.0,
                reasoning="No retrieved context to anchor the answer.",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

        supported = len(answer_tokens & ctx_tokens) / len(answer_tokens)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return EvaluationOutput(
            name=self.name,
            score=round(supported, 4),
            reasoning=f"{int(supported * 100)}% of answer tokens supported by context.",
            latency_ms=latency_ms,
        )
