"""Embedder protocol + LiteLLM-backed implementation.

The :class:`Embedder` protocol abstracts over OpenAI, Ollama, Cohere, etc.
The :class:`LiteLLMEmbedder` implementation routes via LiteLLM's
``aembedding`` for unified provider handling, batching, and retries.

Per ADR-0020, the platform supports embedding dimensions 768, 1024, and 1536.
The :data:`EMBEDDER_DIMENSIONS` table is the canonical mapping from model
alias (the string we persist in ``chunk_embeddings.embedding_model``) to
dimension.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

import litellm
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sentinelrag_shared.llm.types import EmbeddingResult, UsageRecord


class EmbedderError(Exception):
    """Raised when an embedding call cannot be completed after retries."""


# Canonical model -> dimension lookup. Adding a model means adding an entry
# here AND ensuring the migration covers its dimension (ADR-0020 supports
# 768/1024/1536 in v1).
EMBEDDER_DIMENSIONS: dict[str, int] = {
    "ollama/nomic-embed-text": 768,
    "ollama/mxbai-embed-large": 1024,
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 1536,  # truncated; full is 3072 (unsupported)
}


class Embedder(Protocol):
    """Protocol for batch text -> dense vector embedding."""

    model_name: str
    dimension: int

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...


class LiteLLMEmbedder:
    """LiteLLM-routed embedder.

    Args:
        model_name: LiteLLM model alias, e.g. ``"ollama/nomic-embed-text"``.
        api_base: Optional base URL override (set for Ollama running outside
            localhost defaults).
        api_key: Optional API key (read from env when None for cloud providers).
        max_batch_size: LiteLLM client-side batches above this size into chunks.
        request_timeout_seconds: Per-call timeout.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        max_batch_size: int = 64,
        request_timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        if model_name not in EMBEDDER_DIMENSIONS:
            msg = (
                f"Unknown embedding model {model_name!r}. Add it to "
                "EMBEDDER_DIMENSIONS and ensure the migration covers its dim."
            )
            raise ValueError(msg)
        self.model_name = model_name
        self.dimension = EMBEDDER_DIMENSIONS[model_name]
        self._api_base = api_base
        self._api_key = api_key
        self._max_batch = max_batch_size
        self._timeout = request_timeout_seconds
        self._max_retries = max_retries

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model_name=self.model_name,
                dimension=self.dimension,
                usage=UsageRecord(
                    usage_type="embedding",
                    provider=self._provider(),
                    model_name=self.model_name,
                ),
            )

        all_vectors: list[list[float]] = []
        total_input_tokens = 0
        total_cost = Decimal(0)
        start = time.perf_counter()

        # Batch client-side; LiteLLM also batches but we control the chunk size
        # to bound memory and concurrency.
        for chunk_start in range(0, len(texts), self._max_batch):
            chunk = list(texts[chunk_start : chunk_start + self._max_batch])
            response = await self._call_with_retries(chunk)

            for item in response["data"]:
                vec = list(item["embedding"])
                if len(vec) != self.dimension:
                    msg = (
                        f"Embedder returned dim={len(vec)} for {self.model_name!r}; "
                        f"EMBEDDER_DIMENSIONS says {self.dimension}. "
                        "Either the model alias is wrong or the table needs updating."
                    )
                    raise EmbedderError(msg)
                all_vectors.append(vec)

            usage = response.get("usage") or {}
            total_input_tokens += usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
            hidden = response.get("_hidden_params", {}) or {}
            response_cost = hidden.get("response_cost")
            if isinstance(response_cost, (int, float, Decimal)):
                total_cost += Decimal(str(response_cost))

        latency_ms = int((time.perf_counter() - start) * 1000)
        return EmbeddingResult(
            vectors=all_vectors,
            model_name=self.model_name,
            dimension=self.dimension,
            usage=UsageRecord(
                usage_type="embedding",
                provider=self._provider(),
                model_name=self.model_name,
                input_tokens=total_input_tokens,
                total_cost_usd=total_cost if total_cost > 0 else None,
                latency_ms=latency_ms,
            ),
        )

    async def _call_with_retries(self, chunk: list[str]) -> dict:
        kwargs: dict = {
            "model": self.model_name,
            "input": chunk,
            "timeout": self._timeout,
        }
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._api_key:
            kwargs["api_key"] = self._api_key

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    return await litellm.aembedding(**kwargs)
        except Exception as exc:
            msg = f"Embedder {self.model_name!r} failed after {self._max_retries} attempts."
            raise EmbedderError(msg) from exc
        # Unreachable, but makes the type checker happy.
        msg = "litellm.aembedding returned no result."
        raise EmbedderError(msg)

    def _provider(self) -> str:
        # Model aliases use ``provider/name`` form.
        return self.model_name.split("/", 1)[0] if "/" in self.model_name else "unknown"
