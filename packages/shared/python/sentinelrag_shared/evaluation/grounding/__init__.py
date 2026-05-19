"""Online-cascade hallucination adapters (ADR-0010).

These adapters service the live ``/query`` cascade in
``apps/api/app/services/rag/stages/grounding.py``. They're intentionally
separate from the offline ragas-style ``Evaluator`` Protocol in
``sentinelrag_shared.evaluation`` because the shapes differ:

- Offline evaluators take an :class:`EvalCase` + :class:`EvalContext`
  with case_ids, expected answers, and rubrics.
- Online cascade adapters take ``(answer_text, context_text)`` and return
  a categorical verdict + optional reasoning. No case ids; the hot path
  has no time for them.
"""

from sentinelrag_shared.evaluation.grounding.judge import (
    Judge,
    LiteLLMJudge,
    NoOpJudge,
)
from sentinelrag_shared.evaluation.grounding.nli import (
    NliBackend,
    NoOpNliBackend,
)
from sentinelrag_shared.evaluation.grounding.types import (
    JudgeResult,
    JudgeVerdict,
    NliResult,
    NliVerdict,
)

__all__ = [
    "Judge",
    "JudgeResult",
    "JudgeVerdict",
    "LiteLLMJudge",
    "NliBackend",
    "NliResult",
    "NliVerdict",
    "NoOpJudge",
    "NoOpNliBackend",
]
