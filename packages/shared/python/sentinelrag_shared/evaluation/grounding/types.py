"""Verdict types for the online hallucination cascade.

Verdict literals map 1:1 to the CHECK constraint on
``generated_answers.nli_verdict`` / ``generated_answers.judge_verdict``
(see migration 0016). Adding a new literal here requires a parallel
migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NliVerdict = Literal["entail", "neutral", "contradict", "skipped"]
JudgeVerdict = Literal["pass", "fail", "skipped"]


@dataclass(frozen=True, slots=True)
class NliResult:
    verdict: NliVerdict
    confidence: float | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class JudgeResult:
    verdict: JudgeVerdict
    reasoning: str | None = None
    latency_ms: int | None = None
