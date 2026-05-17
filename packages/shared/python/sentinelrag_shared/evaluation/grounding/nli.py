"""NLI backend Protocol + no-op default.

The Protocol classifies (answer, context) into one of
``{entail, neutral, contradict}`` — ``skipped`` is reserved for the
caller when the cascade flag is on but no real backend is wired.

The real deberta-v3 cross-encoder backend lives in the retrieval-service
pod (same model-loading pattern as bge-reranker). For unit tests and
local dev where the model isn't available, the orchestrator defaults to
:class:`NoOpNliBackend`, which returns ``skipped`` so the persisted
verdict makes "we tried but had no backend" visible.
"""

from __future__ import annotations

from typing import Protocol

from sentinelrag_shared.evaluation.grounding.types import NliResult


class NliBackend(Protocol):
    """Classify a (premise=context, hypothesis=answer) pair."""

    async def classify(self, *, answer: str, context: str) -> NliResult: ...


class NoOpNliBackend:
    """Returns ``skipped`` — used when no real model is wired.

    The orchestrator persists the ``skipped`` verdict so the trace makes
    it obvious that the NLI layer was requested but couldn't run, rather
    than misleading the reader into thinking the answer is supported.
    """

    async def classify(self, *, answer: str, context: str) -> NliResult:
        del answer, context
        return NliResult(verdict="skipped", confidence=None, latency_ms=0)
