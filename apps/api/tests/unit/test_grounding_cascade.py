"""R2.S1/S2: per-layer hallucination cascade tests + default-trio assertion.

These tests guard the contract from ADR-0010 § Implementation notes:

1. Layer 1 always runs and sets ``grounding_score``.
2. Layer 2 runs iff the NLI flag is on (default on).
3. Layer 3 runs iff the judge flag is on AND
   (NLI verdict ∈ {neutral, contradict, skipped} OR
    a per-query coin flip lands under ``judge.sample_rate``).
4. Cascade is short-circuited on abstention, empty answer, or empty
   context.
5. The Unleash default trio is exactly
   ``{nli=on, judge=off, judge_sample_rate=0.0}``. A future
   flag-server misconfig that flips judge on at 100% sampling without
   editing this defaults map will fail the asserted-defaults test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.services.rag.stages.grounding import GroundingStage
from app.services.rag.types import (
    ABSTAIN_ANSWER,
    GenerationConfig,
    QueryContext,
    QueryOptions,
    RetrievalConfig,
)
from sentinelrag_shared.evaluation.grounding import (
    JudgeResult,
    NliResult,
)
from sentinelrag_shared.feature_flags import (
    HALLUCINATION_CASCADE_DEFAULTS,
    HALLUCINATION_JUDGE_ENABLED,
    HALLUCINATION_JUDGE_SAMPLE_RATE,
    HALLUCINATION_NLI_ENABLED,
    StaticFeatureFlags,
    resolve_hallucination_flags,
)

# ---------- fixtures ----------


@dataclass
class _FakeAuth:
    tenant_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)


def _ctx(*, answer: str = "answer body", context: str = "supporting context") -> QueryContext:
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
    ctx.answer_text = answer
    ctx.context_text = context
    return ctx


class _FakeNli:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict
        self.calls = 0

    async def classify(self, *, answer: str, context: str) -> NliResult:
        del answer, context
        self.calls += 1
        return NliResult(verdict=self._verdict, confidence=0.9, latency_ms=12)  # type: ignore[arg-type]


class _FakeJudge:
    def __init__(self, verdict: str = "pass") -> None:
        self._verdict = verdict
        self.calls = 0

    async def judge(self, *, query: str, context: str, answer: str) -> JudgeResult:
        del query, context, answer
        self.calls += 1
        return JudgeResult(verdict=self._verdict, reasoning="ok", latency_ms=30)  # type: ignore[arg-type]


# ---------- R2.S2: asserted defaults ----------


@pytest.mark.unit
def test_hallucination_cascade_defaults_are_safe() -> None:
    """A flag-server misconfig must not silently turn the judge on.

    If this test fails, somebody edited the defaults map without
    landing an ADR change. Read ADR-0010's "Implementation notes
    (2026-05-17)" section before flipping these.
    """
    assert HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_NLI_ENABLED] is True
    assert HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_JUDGE_ENABLED] is False
    assert HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_JUDGE_SAMPLE_RATE] == 0.0


@pytest.mark.unit
def test_resolve_hallucination_flags_uses_documented_defaults() -> None:
    flags = resolve_hallucination_flags(StaticFeatureFlags())
    assert flags.nli_enabled is True
    assert flags.judge_enabled is False
    assert flags.judge_sample_rate == 0.0


@pytest.mark.unit
def test_resolve_hallucination_flags_clamps_sample_rate() -> None:
    """A bad config (rate=100 meaning 10,000%) must not exfiltrate cost."""
    over = StaticFeatureFlags({HALLUCINATION_JUDGE_SAMPLE_RATE: 100.0})
    assert resolve_hallucination_flags(over).judge_sample_rate == 1.0
    under = StaticFeatureFlags({HALLUCINATION_JUDGE_SAMPLE_RATE: -0.5})
    assert resolve_hallucination_flags(under).judge_sample_rate == 0.0


# ---------- R2.S1: layer-1 baseline + short-circuit guards ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_layer1_runs_unconditionally() -> None:
    nli = _FakeNli("entail")
    judge = _FakeJudge()
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags({HALLUCINATION_NLI_ENABLED: False}),
    )
    ctx = _ctx(answer="rollback works", context="rollback documented")
    await stage.run(ctx)
    assert ctx.grounding_score is not None
    assert nli.calls == 0  # flag was off
    assert judge.calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cascade_short_circuits_on_abstain_answer() -> None:
    nli = _FakeNli("entail")
    judge = _FakeJudge()
    stage = GroundingStage(
        nli_backend=nli, judge=judge, flag_client=StaticFeatureFlags()
    )
    ctx = _ctx(answer=ABSTAIN_ANSWER, context="ignored")
    await stage.run(ctx)
    assert nli.calls == 0
    assert judge.calls == 0
    assert ctx.nli_verdict is None
    assert ctx.judge_verdict is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cascade_short_circuits_on_empty_context() -> None:
    nli = _FakeNli("entail")
    stage = GroundingStage(nli_backend=nli, flag_client=StaticFeatureFlags())
    ctx = _ctx(answer="some answer", context="")
    await stage.run(ctx)
    # Layer 1 always runs; with no context tokens the overlap is 0.
    assert ctx.grounding_score == 0.0
    assert nli.calls == 0
    assert ctx.nli_verdict is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cascade_short_circuits_on_empty_answer() -> None:
    nli = _FakeNli("entail")
    stage = GroundingStage(nli_backend=nli, flag_client=StaticFeatureFlags())
    ctx = _ctx(answer="", context="something")
    await stage.run(ctx)
    assert ctx.grounding_score is None
    assert nli.calls == 0


# ---------- R2.S1: NLI dispatch ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nli_runs_with_default_flags() -> None:
    nli = _FakeNli("entail")
    stage = GroundingStage(nli_backend=nli, flag_client=StaticFeatureFlags())
    ctx = _ctx()
    await stage.run(ctx)
    assert nli.calls == 1
    assert ctx.nli_verdict == "entail"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nli_disabled_when_flag_off() -> None:
    nli = _FakeNli("entail")
    stage = GroundingStage(
        nli_backend=nli,
        flag_client=StaticFeatureFlags({HALLUCINATION_NLI_ENABLED: False}),
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert nli.calls == 0
    assert ctx.nli_verdict is None


# ---------- R2.S1: Judge dispatch + sampling ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_skipped_when_master_flag_off() -> None:
    """Judge MUST stay off even if NLI says 'contradict' — master flag wins."""
    nli = _FakeNli("contradict")
    judge = _FakeJudge()
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags(),  # judge.enabled=False default
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert ctx.nli_verdict == "contradict"
    assert judge.calls == 0
    assert ctx.judge_verdict is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_runs_on_high_risk_nli_verdict() -> None:
    """Judge runs unconditionally when NLI flagged a problem, even at 0% sampling."""
    nli = _FakeNli("contradict")
    judge = _FakeJudge(verdict="fail")
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags({HALLUCINATION_JUDGE_ENABLED: True}),
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert judge.calls == 1
    assert ctx.judge_verdict == "fail"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_skipped_on_entail_when_sample_rate_zero() -> None:
    """Healthy NLI + 0% sampling = no judge call, no judge cost."""
    nli = _FakeNli("entail")
    judge = _FakeJudge(verdict="pass")
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags({HALLUCINATION_JUDGE_ENABLED: True}),
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert judge.calls == 0
    assert ctx.judge_verdict is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_runs_on_sample_hit_with_entail() -> None:
    nli = _FakeNli("entail")
    judge = _FakeJudge(verdict="pass")
    samples: list[float] = [0.05]  # below sample_rate
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags(
            {
                HALLUCINATION_JUDGE_ENABLED: True,
                HALLUCINATION_JUDGE_SAMPLE_RATE: 0.1,
            }
        ),
        sampler=lambda: samples.pop(0),
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert judge.calls == 1
    assert ctx.judge_verdict == "pass"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_skipped_on_sample_miss_with_entail() -> None:
    nli = _FakeNli("entail")
    judge = _FakeJudge(verdict="pass")
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags(
            {
                HALLUCINATION_JUDGE_ENABLED: True,
                HALLUCINATION_JUDGE_SAMPLE_RATE: 0.1,
            }
        ),
        sampler=lambda: 0.9,  # above sample_rate
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert judge.calls == 0
    assert ctx.judge_verdict is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_judge_runs_when_nli_is_skipped_backend() -> None:
    """If NLI was requested but skipped (no real backend), judge picks up the slack."""
    nli = _FakeNli("skipped")
    judge = _FakeJudge(verdict="pass")
    stage = GroundingStage(
        nli_backend=nli,
        judge=judge,
        flag_client=StaticFeatureFlags({HALLUCINATION_JUDGE_ENABLED: True}),
    )
    ctx = _ctx()
    await stage.run(ctx)
    assert judge.calls == 1


# ---------- defaults integration: zero-config GroundingStage ----------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_construction_is_safe() -> None:
    """A GroundingStage built with no args runs layer 1, NLI-skipped, judge off."""
    stage = GroundingStage()
    ctx = _ctx(answer="rollback procedure", context="rollback procedure documented")
    await stage.run(ctx)
    assert ctx.grounding_score is not None
    assert ctx.nli_verdict == "skipped"  # NoOpNliBackend, flag default on
    assert ctx.judge_verdict is None  # judge flag default off
    assert ctx.judge_reasoning is None


@pytest.mark.unit
def test_static_feature_flags_returns_defaults_when_unset() -> None:
    client = StaticFeatureFlags()
    assert client.bool_flag("missing", default=True) is True
    assert client.bool_flag("missing", default=False) is False
    assert client.float_flag("missing", default=0.42) == 0.42


@pytest.mark.unit
def test_static_feature_flags_honors_overrides() -> None:
    client = StaticFeatureFlags({"a": False, "b": 0.7})
    assert client.bool_flag("a", default=True) is False
    assert client.float_flag("b", default=0.0) == 0.7


@pytest.mark.unit
def test_static_feature_flags_set_updates_value() -> None:
    client = StaticFeatureFlags()
    client.set("k", True)
    assert client.bool_flag("k", default=False) is True


@pytest.mark.unit
def test_static_feature_flags_ignores_context_kwarg() -> None:
    client = StaticFeatureFlags()
    ctx: dict[str, Any] = {"tenant_id": "anything"}
    assert client.bool_flag("k", default=True, context=ctx) is True
