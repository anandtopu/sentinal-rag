"""Generator protocol + LiteLLM-backed implementation (ADR-0005, ADR-0014).

Mirrors :class:`Embedder`'s shape — single async ``complete()`` call that
returns a :class:`GenerationResult` with usage accounting.

Per ADR-0014, the system default is ``ollama/llama3.1:8b``; tenants with
``llm:cloud_models`` permission can opt into ``openai/gpt-4.1-mini``,
``anthropic/claude-haiku-4-5``, etc. via the per-request override.

LiteLLM exposes a unified ``acompletion`` API across providers — this thin
wrapper adds tenacity-based retries, bounded timeouts, and uniform
``UsageRecord`` extraction.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Protocol

import litellm
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sentinelrag_shared.llm.types import GenerationResult, UsageRecord


class GeneratorError(Exception):
    """Raised when generation fails after retries."""


class Generator(Protocol):
    """Protocol for LLM completion."""

    model_name: str

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> GenerationResult: ...


class LiteLLMGenerator:
    """LiteLLM-routed generator.

    Args:
        model_name: LiteLLM alias, e.g. ``"ollama/llama3.1:8b"``,
            ``"openai/gpt-4.1-mini"``, ``"anthropic/claude-haiku-4-5"``.
        api_base: Optional override (set for Ollama running outside default).
        api_key: Optional API key (read from env when None for cloud providers).
        request_timeout_seconds: Per-call timeout.
        max_retries: Total attempts including the first.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        request_timeout_seconds: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.model_name = model_name
        self._api_base = api_base
        self._api_key = api_key
        self._timeout = request_timeout_seconds
        self._max_retries = max_retries

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> GenerationResult:
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": self._timeout,
        }
        if stop:
            kwargs["stop"] = stop
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._api_key:
            kwargs["api_key"] = self._api_key

        start = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    response = await litellm.acompletion(**kwargs)
                    break
            else:
                # never reached because reraise=True; satisfy the type checker
                msg = "litellm.acompletion returned no result."
                raise GeneratorError(msg)
        except Exception as exc:
            msg = f"Generator {self.model_name!r} failed after {self._max_retries} attempts."
            raise GeneratorError(msg) from exc

        latency_ms = int((time.perf_counter() - start) * 1000)

        message = response["choices"][0]["message"]
        text = message.get("content") or ""
        finish_reason = response["choices"][0].get("finish_reason")

        usage_obj = response.get("usage") or {}
        input_tokens = int(usage_obj.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage_obj.get("completion_tokens", 0) or 0)

        cost: Decimal | None = None
        hidden = response.get("_hidden_params") or {}
        if isinstance(hidden.get("response_cost"), (int, float, Decimal)):
            cost = Decimal(str(hidden["response_cost"]))

        return GenerationResult(
            text=text,
            finish_reason=finish_reason,
            usage=UsageRecord(
                usage_type="completion",
                provider=self._provider(),
                model_name=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_cost_usd=cost,
                latency_ms=latency_ms,
            ),
        )

    def _provider(self) -> str:
        return self.model_name.split("/", 1)[0] if "/" in self.model_name else "unknown"
