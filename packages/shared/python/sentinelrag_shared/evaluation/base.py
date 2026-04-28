"""Evaluator protocol + shared input/output dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


@dataclass(slots=True)
class EvalCase:
    """The expected behavior side of an evaluation case."""

    case_id: UUID
    input_query: str
    expected_answer: str | None = None
    expected_citation_chunk_ids: list[UUID] = field(default_factory=list)
    grading_rubric: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalContext:
    """The actual behavior side: what the system produced for this case."""

    answer_text: str
    retrieved_chunks: list[dict[str, Any]]  # parallel to ``retrieval_results`` rows
    cited_chunk_ids: list[UUID]
    cited_quoted_texts: list[str]


@dataclass(slots=True)
class EvaluationOutput:
    """Result of one Evaluator on one (case, context) pair."""

    name: str
    score: float | None  # in [0, 1] if computable
    reasoning: str | None = None
    latency_ms: int | None = None
    cost_usd: Decimal | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    """Score the quality of a system response against an evaluation case."""

    name: str

    async def evaluate(
        self,
        *,
        case: EvalCase,
        context: EvalContext,
    ) -> EvaluationOutput: ...
