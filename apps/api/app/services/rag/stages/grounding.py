"""GroundingStage — three-layer hallucination cascade (ADR-0010).

Layer 1 (always on): token-overlap → ``ctx.grounding_score``.
Layer 2 (Unleash-gated): NLI verdict over (context, answer) →
  ``ctx.nli_verdict``.
Layer 3 (Unleash-gated + risk-driven + sampled): LLM-as-judge verdict +
  reasoning → ``ctx.judge_verdict`` / ``ctx.judge_reasoning``.

Cascade is short-circuited when no answer was generated (empty or
abstention). Persisted verdict semantics:

- ``None`` — layer never ran (flag off, or cascade short-circuited).
- ``"skipped"`` — flag was on but no real backend was wired, or the
  layer's call raised. Tells the operator "we tried, fix the wiring."
- categorical verdict — actual classifier output.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from sentinelrag_shared.evaluation.grounding import (
    Judge,
    NliBackend,
    NoOpJudge,
    NoOpNliBackend,
)
from sentinelrag_shared.feature_flags import (
    FeatureFlagClient,
    StaticFeatureFlags,
    resolve_hallucination_flags,
)
from sentinelrag_shared.telemetry import record_hallucination_layer_latency

from app.services.rag._helpers import token_overlap_score
from app.services.rag.types import ABSTAIN_ANSWER, QueryContext


class GroundingStage:
    """Run the layered hallucination cascade end-to-end.

    Args:
        nli_backend: Layer-2 classifier. Defaults to a no-op so unit
            tests don't pay for a real model.
        judge: Layer-3 LLM judge. Defaults to a no-op.
        flag_client: Reads the cascade flags + sample rate. Defaults to
            a static client that returns the documented defaults.
        sampler: Optional ``() -> float in [0,1]`` for deterministic
            tests. Defaults to :func:`random.random`.
    """

    def __init__(
        self,
        *,
        nli_backend: NliBackend | None = None,
        judge: Judge | None = None,
        flag_client: FeatureFlagClient | None = None,
        sampler: Callable[[], float] | None = None,
    ) -> None:
        self._nli = nli_backend or NoOpNliBackend()
        self._judge = judge or NoOpJudge()
        self._flags = flag_client or StaticFeatureFlags()
        self._sampler = sampler or random.random

    async def run(self, ctx: QueryContext) -> None:
        # Layer 1 — always on.
        overlap_start = time.perf_counter()
        ctx.grounding_score = token_overlap_score(ctx.answer_text, ctx.context_text)
        record_hallucination_layer_latency(
            layer="overlap",
            latency_ms=int((time.perf_counter() - overlap_start) * 1000),
        )

        if self._should_short_circuit(ctx):
            return

        cascade = resolve_hallucination_flags(
            self._flags,
            context={"tenant_id": str(ctx.auth.tenant_id)},
        )

        if cascade.nli_enabled:
            nli = await self._nli.classify(
                answer=ctx.answer_text, context=ctx.context_text
            )
            ctx.nli_verdict = nli.verdict
            if nli.latency_ms is not None:
                record_hallucination_layer_latency(
                    layer="nli", latency_ms=nli.latency_ms
                )

        if not cascade.judge_enabled:
            return

        if not self._should_judge(ctx.nli_verdict, cascade.judge_sample_rate):
            return

        judgment = await self._judge.judge(
            query=ctx.query,
            context=ctx.context_text,
            answer=ctx.answer_text,
        )
        ctx.judge_verdict = judgment.verdict
        ctx.judge_reasoning = judgment.reasoning
        if judgment.latency_ms is not None:
            record_hallucination_layer_latency(
                layer="judge", latency_ms=judgment.latency_ms
            )

    @staticmethod
    def _should_short_circuit(ctx: QueryContext) -> bool:
        """Skip layers 2+3 when there's nothing meaningful to verify."""
        if not ctx.answer_text.strip():
            return True
        if ctx.answer_text == ABSTAIN_ANSWER:
            return True
        # No retrieved context means NLI/judge have no premise to ground
        # against; their verdicts would be uninformative.
        return not ctx.context_text.strip()

    def _should_judge(
        self, nli_verdict: str | None, sample_rate: float
    ) -> bool:
        """Judge runs on high-risk verdicts OR on a sampled fraction."""
        if nli_verdict in {"neutral", "contradict", "skipped"}:
            return True
        if sample_rate <= 0:
            return False
        return self._sampler() < sample_rate
