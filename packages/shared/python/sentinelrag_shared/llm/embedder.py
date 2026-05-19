from __future__ import annotations

import litellm
from collections.abc import Mapping, Sequence
from decimal import Decimal
from time import perf_counter
from typing import Any

from sentinelrag_shared.llm.types import EmbeddingResult, UsageRecord


class EmbedderError(RuntimeError):
    """Base embedder error."""


class Embedder:
    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:  # pragma: no cover
        raise NotImplementedError


def _infer_provider(model_name: str, provider: str | None) -> str | None:
    if provider:
        return provider
    if "/" in model_name:
        return model_name.split("/", 1)[0]
    return None


def _default_dimension(model_name: str) -> int:
    lowered = model_name.lower()
    if "nomic-embed-text" in lowered:
        return 768
    if "bge-m3" in lowered:
        return 1024
    return 768


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


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(str(value))
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal("0")


class LiteLLMEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        provider: str | None = None,
        batch_size: int = 32,
        max_batch_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.provider = _infer_provider(model_name, provider)
        self.batch_size = max_batch_size or batch_size
        self.kwargs: dict[str, Any] = dict(kwargs)
        self.expected_dimension = _default_dimension(model_name)

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model_name=self.model_name,
                dimension=self.expected_dimension,
                provider=self.provider,
                usage=UsageRecord(
                    usage_type="embedding",
                    provider=self.provider,
                    model_name=self.model_name,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    total_cost_usd=Decimal("0"),
                    latency_ms=0,
                ),
            )

        started = perf_counter()
        vectors: list[list[float]] = []
        total_input_tokens = 0
        total_tokens = 0
        total_cost = Decimal("0")
        resolved_model = self.model_name

        for i in range(0, len(texts), self.batch_size):
            chunk = list(texts[i : i + self.batch_size])
            try:
                raw_response = await litellm.aembedding(
                    model=self.model_name,
                    input=chunk,
                    **self.kwargs,
                )
            except Exception as exc:
                raise EmbedderError(str(exc)) from exc

            response = _as_mapping(raw_response)

            response_model = response.get("model")
            if isinstance(response_model, str) and response_model:
                resolved_model = response_model

            data = response.get("data", [])
            if not isinstance(data, Sequence):
                data = []

            for item in data:
                item_map = _as_mapping(item)
                embedding = item_map.get("embedding", [])
                if isinstance(embedding, Sequence):
                    vector = [float(x) for x in embedding]
                    if len(vector) != self.expected_dimension:
                        raise EmbedderError(
                            f"{self.model_name} returned dim={len(vector)} expected dim={self.expected_dimension}"
                        )
                    vectors.append(vector)

            usage = _as_mapping(response.get("usage"))
            prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            total_input_tokens += (
                int(prompt_tokens) if isinstance(prompt_tokens, int | float) else 0
            )

            total_tok = usage.get("total_tokens")
            if isinstance(total_tok, int | float):
                total_tokens += int(total_tok)
            else:
                total_tokens += int(prompt_tokens) if isinstance(prompt_tokens, int | float) else 0

            hidden = _as_mapping(response.get("_hidden_params"))
            total_cost += _as_decimal(hidden.get("response_cost", 0))

        dimension = len(vectors[0]) if vectors else _default_dimension(self.model_name)
        latency_ms = int((perf_counter() - started) * 1000)

        return EmbeddingResult(
            vectors=vectors,
            model_name=resolved_model,
            dimension=self.expected_dimension,
            provider=self.provider,
            usage=UsageRecord(
                usage_type="embedding",
                provider=self.provider,
                model_name=resolved_model,
                input_tokens=total_input_tokens,
                output_tokens=0,
                total_tokens=total_tokens,
                total_cost_usd=total_cost,
                latency_ms=latency_ms,
            ),
        )
