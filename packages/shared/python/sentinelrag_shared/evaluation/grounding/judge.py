"""LLM-as-judge cascade layer (ADR-0010 layer 3).

The :class:`LiteLLMJudge` builds a structured prompt asking the model to
emit a categorical PASS/FAIL verdict + a one-line reason, then parses
the response. It accepts any :class:`Generator` so the same code path
serves Ollama (local demo), OpenAI, and Anthropic.

For unit tests there's a :class:`NoOpJudge` returning ``skipped`` — same
escape hatch the NLI layer uses.
"""

from __future__ import annotations

import re
import time
from typing import Protocol

from sentinelrag_shared.evaluation.grounding.types import JudgeResult, JudgeVerdict
from sentinelrag_shared.llm.generator import Generator, GeneratorError

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict factual grounding judge. Given a question, the "
    "context retrieved to answer it, and the generated answer, decide if "
    "every factual claim in the answer is directly supported by the "
    "context. Reply on the first line with exactly 'PASS' or 'FAIL', then "
    "one short reason on the second line. Do not invent facts; if you "
    "cannot find support, the verdict is FAIL."
)


_JUDGE_USER_TEMPLATE = (
    "QUESTION:\n{query}\n\n"
    "CONTEXT:\n{context}\n\n"
    "ANSWER:\n{answer}\n\n"
    "Reply now in the required format."
)


_VERDICT_RE = re.compile(r"\b(PASS|FAIL)\b", re.IGNORECASE)

# Minimum number of non-empty lines the judge output must have for us to
# treat the second line as the reason.
_MIN_LINES_WITH_REASON = 2


class Judge(Protocol):
    """Categorical pass/fail judgment over (query, context, answer)."""

    async def judge(
        self, *, query: str, context: str, answer: str
    ) -> JudgeResult: ...


class NoOpJudge:
    """Stub used when no judge model is wired in.

    Returns ``skipped`` so persisted rows tell the truth.
    """

    async def judge(
        self, *, query: str, context: str, answer: str
    ) -> JudgeResult:
        del query, context, answer
        return JudgeResult(verdict="skipped", reasoning=None, latency_ms=0)


class LiteLLMJudge:
    """LLM-judge backed by a SentinelRAG :class:`Generator`.

    The model alias is whatever the operator wires (typically a stronger
    model than the generator — Sonnet to grade Haiku, etc.). The judge
    prompt is static (cost-bounded); a future ADR can promote it to the
    versioned prompt registry if recruiters ask.
    """

    def __init__(
        self,
        *,
        generator: Generator,
        temperature: float = 0.0,
        max_tokens: int = 120,
    ) -> None:
        self._generator = generator
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def judge(
        self, *, query: str, context: str, answer: str
    ) -> JudgeResult:
        user_prompt = _JUDGE_USER_TEMPLATE.format(
            query=query.strip(),
            context=context.strip(),
            answer=answer.strip(),
        )
        start = time.perf_counter()
        try:
            result = await self._generator.complete(
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except GeneratorError:
            return JudgeResult(
                verdict="skipped",
                reasoning="judge model failed",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        latency_ms = int((time.perf_counter() - start) * 1000)
        verdict_match = _VERDICT_RE.search(result.text or "")
        if verdict_match is None:
            # The judge output didn't parse — record as skipped rather than
            # forcing a verdict we don't actually have.
            return JudgeResult(
                verdict="skipped",
                reasoning=(result.text or "")[:200] or "unparseable",
                latency_ms=latency_ms,
            )
        verdict: JudgeVerdict = (
            "pass" if verdict_match.group(1).upper() == "PASS" else "fail"
        )
        reasoning = _extract_reason(result.text or "")
        return JudgeResult(
            verdict=verdict,
            reasoning=reasoning,
            latency_ms=latency_ms,
        )


def _extract_reason(text: str) -> str | None:
    """Pull the reason line after the verdict; cap length for storage."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= _MIN_LINES_WITH_REASON:
        return lines[1][:500]
    return None
