# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol, cast

import litellm

from sentinelrag_shared.llm.types import GenerateResult, UsageRecord


class GeneratorError(Exception):
    """Raised when text generation fails."""
    pass


class GeneratorTimeoutError(GeneratorError):
    """Raised when text generation times out."""
    pass


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
    def _provider(self) -> str:
        return self.model_name.split("/", 1)[0] if "/" in self.model_name else "litellm"

    def __init__(
        self,
        *,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
    ) -> None:
        self.model_name = model_name
        self.api_base = api_base
        self.api_key = api_key
        self.max_retries = max_retries

    async def complete(
        self,
        *,
        system_prompt: str | None,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        stop: Sequence[str] | None = None,
    ) -> GenerateResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        return await self._run_completion(
            system_prompt=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        )

    async def generate(
        self,
        *,
        system_prompt: str | None,
        messages: Sequence[Mapping[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> GenerateResult:
        return await self._run_completion(
            system_prompt=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=None,
        )

    async def _run_completion(
        self,
        *,
        system_prompt: str | None,
        messages: Sequence[Mapping[str, Any]],
        temperature: float,
        max_tokens: int,
        stop: Sequence[str] | None,
    ) -> GenerateResult:
        payload: list[dict[str, Any]] = []

        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})

        payload.extend(dict(message) for message in messages)

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": payload,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "num_retries": self.max_retries,
        }
        if stop:
            kwargs["stop"] = list(stop)
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        try:
            response_obj = await litellm.acompletion(**kwargs)
        except TimeoutError as exc:
            raise GeneratorTimeoutError(
                f"LiteLLM generation timed out after {self.max_retries} attempts: {exc}"
            ) from exc
        except Exception as exc:
            if "timeout" in str(exc).lower():
                raise GeneratorTimeoutError(
                    f"LiteLLM generation timed out after {self.max_retries} attempts: {exc}"
                ) from exc
            raise GeneratorError(
                f"LiteLLM generation failed after {self.max_retries} attempts: {exc}"
            ) from exc

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
        total_cost_usd = (
            Decimal(str(response_cost))
            if isinstance(response_cost, (int, float, Decimal))
            else None
        )

        return GenerateResult(
            text=text,
            finish_reason=finish_reason,
            model_name=self.model_name,
            usage=UsageRecord(
                usage_type="generation",
                provider=self._provider(),
                model_name=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                total_cost_usd=total_cost_usd,
            ),
        )
