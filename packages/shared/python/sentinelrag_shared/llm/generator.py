from __future__ import annotations

import litellm
from collections.abc import Mapping, Sequence
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol

from sentinelrag_shared.llm.types import GenerationResult, JsonValue, UsageRecord


class GeneratorError(RuntimeError):
    """Base generator error."""


class _Message(Protocol):
    content: str | None


class _Choice(Protocol):
    message: _Message
    finish_reason: str | None


class _CompletionUsage(Protocol):
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class Generator(Protocol):
    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> GenerationResult: ...


def _infer_provider(model_name: str, provider: str | None) -> str | None:
    if provider:
        return provider
    if "/" in model_name:
        return model_name.split("/", 1)[0]
    return None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    if hasattr(value, "__dict__"):
        data = vars(value)
        if isinstance(data, Mapping):
            return data
    return {}


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        return Decimal(str(value))
    return None


class LiteLLMGenerator:
    def __init__(
        self,
        model_name: str,
        *,
        provider: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.provider = _infer_provider(model_name, provider)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.kwargs: dict[str, Any] = dict(kwargs)

    async def generate(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> GenerationResult:
        started = perf_counter()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            raw_response = await litellm.acompletion(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                metadata=dict(metadata or {}),
                **self.kwargs,
            )
        except Exception as exc:
            raise GeneratorError(str(exc)) from exc

        response = _as_mapping(raw_response)
        choices = response.get("choices", [])
        if not isinstance(choices, Sequence) or not choices:
            raise GeneratorError(f"{self.model_name} returned no choices")

        first_choice = _as_mapping(choices[0])
        message = _as_mapping(first_choice.get("message"))
        content = message.get("content")
        if not isinstance(content, str):
            raise GeneratorError(f"{self.model_name} returned empty content")

        usage = _as_mapping(response.get("usage"))
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens")
        if not isinstance(total_tokens, int | float):
            total_tokens = (int(input_tokens) if isinstance(input_tokens, int | float) else 0) + (
                int(output_tokens) if isinstance(output_tokens, int | float) else 0
            )

        hidden = _as_mapping(response.get("_hidden_params"))
        total_cost = _as_decimal(hidden.get("response_cost"))
        latency_ms = int((perf_counter() - started) * 1000)

        return GenerationResult(
            text=content,
            model_name=self.model_name,
            provider=self.provider,
            finish_reason=first_choice.get("finish_reason"),
            usage=UsageRecord(
                usage_type="generation",
                provider=self.provider,
                model_name=self.model_name,
                input_tokens=int(input_tokens) if isinstance(input_tokens, int | float) else 0,
                output_tokens=int(output_tokens) if isinstance(output_tokens, int | float) else 0,
                total_tokens=int(total_tokens) if isinstance(total_tokens, int | float) else 0,
                total_cost_usd=total_cost,
                latency_ms=latency_ms,
                extra={"metadata": dict(metadata or {})},
            ),
        )
