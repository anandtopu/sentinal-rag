from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any, Protocol, cast

from litellm import aembedding as litellm_aembedding

from sentinelrag_shared.llm.types import EmbeddingResult, UsageRecord


class _EmbeddingDataItem(Protocol):
    embedding: Sequence[float]


class _EmbeddingUsage(Protocol):
    prompt_tokens: int | None
    total_tokens: int | None


class _EmbeddingResponse(Protocol):
    data: Sequence[_EmbeddingDataItem]
    model: str | None
    usage: _EmbeddingUsage | None


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...


class LiteLLMEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        provider: str | None = None,
        batch_size: int = 32,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.provider = provider
        self.batch_size = batch_size
        self.kwargs: dict[str, Any] = dict(kwargs)

    async def _embed_once(self, chunk: Sequence[str]) -> _EmbeddingResponse:
        response = await cast(Any, litellm_aembedding)(
            model=self.model_name,
            input=list(chunk),
            **self.kwargs,
        )
        return cast(_EmbeddingResponse, response)

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        started = perf_counter()

        all_vectors: list[list[float]] = []
        total_input_tokens = 0
        total_tokens = 0
        resolved_model = self.model_name

        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            response = await self._embed_once(chunk)
            resolved_model = response.model or resolved_model

            for item in response.data:
                all_vectors.append([float(x) for x in item.embedding])

            usage = response.usage
            if usage is not None:
                total_input_tokens += usage.prompt_tokens or 0
                total_tokens += usage.total_tokens or 0

        latency_ms = int((perf_counter() - started) * 1000)
        dimension = len(all_vectors[0]) if all_vectors else 0

        return EmbeddingResult(
            vectors=all_vectors,
            model_name=resolved_model,
            dimension=dimension,
            provider=self.provider,
            usage=UsageRecord(
                usage_type="embedding",
                provider=self.provider,
                model_name=resolved_model,
                input_tokens=total_input_tokens,
                output_tokens=0,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            ),
        )
