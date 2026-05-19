from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any, Protocol, cast

from litellm import acompletion as litellm_acompletion

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


class _CompletionResponse(Protocol):
    choices: Sequence[_Choice]
    model: str | None
    usage: _CompletionUsage | None

    def model_dump(self) -> dict[str, Any]: ...


class Generator(Protocol):
    async def generate(self, messages: Sequence[dict[str, str]]) -> GenerationResult: ...


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            result[str(key)] = _coerce_json_value(item)
        return result
    return str(value)


def _coerce_json_dict(value: Mapping[str, object]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        result[str(key)] = _coerce_json_value(item)
    return result


class LiteLLMGenerator:
    def __init__(
        self,
        model_name: str,
        *,
        provider: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.provider = provider
        self.kwargs: dict[str, Any] = dict(kwargs)

    async def generate(self, messages: Sequence[dict[str, str]]) -> GenerationResult:
        started = perf_counter()

        try:
            response = cast(
                _CompletionResponse,
                await cast(Any, litellm_acompletion)(
                    model=self.model_name,
                    messages=list(messages),
                    **self.kwargs,
                ),
            )
        except Exception as exc:
            raise GeneratorError(str(exc)) from exc

        first_choice = response.choices[0]
        text = first_choice.message.content or ""
        finish_reason = first_choice.finish_reason
        resolved_model = response.model or self.model_name

        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        usage = response.usage
        if usage is not None:
            input_tokens = usage.prompt_tokens or 0
            output_tokens = usage.completion_tokens or 0
            total_tokens = usage.total_tokens or (input_tokens + output_tokens)

        latency_ms = int((perf_counter() - started) * 1000)

        raw_dump = cast(Mapping[str, object], response.model_dump())
        raw_response = _coerce_json_dict(raw_dump)

        return GenerationResult(
            text=text,
            model_name=resolved_model,
            provider=self.provider,
            finish_reason=finish_reason,
            usage=UsageRecord(
                usage_type="generation",
                provider=self.provider,
                model_name=resolved_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            ),
            raw_response=raw_response,
        )
