# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from litellm import acompletion

from sentinelrag_shared.llm.types import GenerateResult, UsageRecord


class Generator(Protocol):
    model_name: str

    async def generate(
        self,
        *,
        system_prompt: str | None,
        messages: Sequence[Mapping[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> GenerateResult: ...


class LiteLLMGenerator:
    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    async def generate(
        self,
        *,
        system_prompt: str | None,
        messages: Sequence[Mapping[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> GenerateResult:
        payload: list[dict[str, Any]] = []

        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})

        payload.extend(dict(message) for message in messages)

        response_obj = await acompletion(
            model=self.model_name,
            messages=payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response = cast(dict[str, Any], cast(Any, response_obj))

        choices = cast(list[dict[str, Any]], response.get("choices", []))
        first_choice = choices[0] if choices else {}
        message = cast(dict[str, Any], first_choice.get("message", {}))
        text = cast(str, message.get("content", "") or "")
        finish_reason = cast(str | None, first_choice.get("finish_reason"))

        usage_obj = cast(dict[str, Any], response.get("usage", {}))
        input_tokens = int(cast(int | float, usage_obj.get("prompt_tokens", 0) or 0))
        output_tokens = int(
            cast(int | float, usage_obj.get("completion_tokens", 0) or 0)
        )

        hidden = cast(dict[str, Any], response.get("_hidden_params", {}))
        response_cost = hidden.get("response_cost")
        reasoning_tokens = (
            int(cast(int | float | str, response_cost))
            if response_cost is not None
            else None
        )

        return GenerateResult(
            text=text,
            finish_reason=finish_reason,
            model_name=self.model_name,
            usage=UsageRecord(
                usage_type="generation",
                provider="litellm",
                model_name=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            ),
        )
