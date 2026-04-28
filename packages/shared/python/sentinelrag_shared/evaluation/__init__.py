"""Evaluation framework — Evaluator protocol + custom + ragas adapters.

Per ADR-0019, ragas provides the standard 4 metrics; custom evaluators
cover spec-specific signals (citation accuracy, hallucination risk).

For Phase 4 v1 we ship custom token-overlap based evaluators that work
without an external LLM judge — fast and deterministic. ragas-backed
versions are added in Phase 6 alongside the cloud-judge wiring.
"""

from sentinelrag_shared.evaluation.base import (
    EvalCase,
    EvalContext,
    EvaluationOutput,
    Evaluator,
)
from sentinelrag_shared.evaluation.evaluators import (
    AnswerCorrectnessEvaluator,
    CitationAccuracyEvaluator,
    ContextRelevanceEvaluator,
    FaithfulnessEvaluator,
)

__all__ = [
    "AnswerCorrectnessEvaluator",
    "CitationAccuracyEvaluator",
    "ContextRelevanceEvaluator",
    "EvalCase",
    "EvalContext",
    "EvaluationOutput",
    "Evaluator",
    "FaithfulnessEvaluator",
]
