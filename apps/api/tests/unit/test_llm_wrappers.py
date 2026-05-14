"""Unit coverage for shared LLM gateway wrappers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sentinelrag_shared.llm.embedder import EmbedderError, LiteLLMEmbedder
from sentinelrag_shared.llm.generator import GeneratorError, LiteLLMGenerator
from sentinelrag_shared.llm.reranker import BgeReranker, RerankCandidate, RerankerError


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_embedder_empty_input_returns_usage_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("provider should not be called for an empty batch")

    monkeypatch.setattr("sentinelrag_shared.llm.embedder.litellm.aembedding", fail_if_called)
    embedder = LiteLLMEmbedder(model_name="ollama/nomic-embed-text")

    result = await embedder.embed([])

    assert result.vectors == []
    assert result.dimension == 768
    assert result.usage.usage_type == "embedding"
    assert result.usage.provider == "ollama"
    assert result.usage.model_name == "ollama/nomic-embed-text"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_embedder_batches_and_aggregates_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_aembedding(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        batch = kwargs["input"]
        return {
            "data": [{"embedding": [0.25] * 768} for _ in batch],
            "usage": {"prompt_tokens": len(batch) * 7},
            "_hidden_params": {"response_cost": 0.0015},
        }

    monkeypatch.setattr("sentinelrag_shared.llm.embedder.litellm.aembedding", fake_aembedding)
    embedder = LiteLLMEmbedder(
        model_name="ollama/nomic-embed-text",
        api_base="http://ollama:11434",
        api_key="local-key",
        max_batch_size=2,
    )

    result = await embedder.embed(["alpha", "beta", "gamma"])

    assert len(calls) == 2
    assert calls[0]["input"] == ["alpha", "beta"]
    assert calls[1]["input"] == ["gamma"]
    assert calls[0]["api_base"] == "http://ollama:11434"
    assert calls[0]["api_key"] == "local-key"
    assert len(result.vectors) == 3
    assert result.usage.input_tokens == 21
    assert result.usage.total_cost_usd == Decimal("0.0030")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_embedder_rejects_unexpected_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_aembedding(**_kwargs: Any) -> dict[str, Any]:
        return {"data": [{"embedding": [0.1, 0.2]}], "usage": {"input_tokens": 3}}

    monkeypatch.setattr("sentinelrag_shared.llm.embedder.litellm.aembedding", fake_aembedding)
    embedder = LiteLLMEmbedder(model_name="ollama/nomic-embed-text", max_retries=1)

    with pytest.raises(EmbedderError, match="returned dim=2"):
        await embedder.embed(["short vector"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_embedder_wraps_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_aembedding(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("sentinelrag_shared.llm.embedder.litellm.aembedding", fake_aembedding)
    embedder = LiteLLMEmbedder(model_name="ollama/nomic-embed-text", max_retries=1)

    with pytest.raises(EmbedderError, match="failed after 1 attempts") as exc_info:
        await embedder.embed(["hello"])

    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_generator_forwards_request_and_extracts_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {"content": "grounded answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
            "_hidden_params": {"response_cost": Decimal("0.0042")},
        }

    monkeypatch.setattr("sentinelrag_shared.llm.generator.litellm.acompletion", fake_acompletion)
    generator = LiteLLMGenerator(
        model_name="openai/gpt-4.1-mini",
        api_base="https://litellm.example",
        api_key="secret",
    )

    result = await generator.complete(
        system_prompt="Be precise.",
        user_prompt="What changed?",
        temperature=0.2,
        max_tokens=128,
        stop=["END"],
    )

    assert calls[0]["messages"] == [
        {"role": "system", "content": "Be precise."},
        {"role": "user", "content": "What changed?"},
    ]
    assert calls[0]["temperature"] == 0.2
    assert calls[0]["max_tokens"] == 128
    assert calls[0]["stop"] == ["END"]
    assert calls[0]["api_base"] == "https://litellm.example"
    assert calls[0]["api_key"] == "secret"
    assert result.text == "grounded answer"
    assert result.finish_reason == "stop"
    assert result.usage.provider == "openai"
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 5
    assert result.usage.total_cost_usd == Decimal("0.0042")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_generator_wraps_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("timeout")

    monkeypatch.setattr("sentinelrag_shared.llm.generator.litellm.acompletion", fake_acompletion)
    generator = LiteLLMGenerator(model_name="ollama/llama3.1:8b", max_retries=1)

    with pytest.raises(GeneratorError, match="failed after 1 attempts") as exc_info:
        await generator.complete(system_prompt="sys", user_prompt="user")

    assert isinstance(exc_info.value.__cause__, RuntimeError)


class _ComputeScoreModel:
    def compute_score(
        self,
        pairs: list[tuple[str, str]],
        *,
        normalize: bool,
        batch_size: int,
    ) -> list[float]:
        assert pairs == [
            ("query", "least relevant"),
            ("query", "most relevant"),
            ("query", "middle"),
        ]
        assert normalize is True
        assert batch_size == 2
        return [0.1, 0.9, 0.4]


class _PredictModel:
    def predict(
        self,
        pairs: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> list[float]:
        assert pairs == [("query", "alpha"), ("query", "beta")]
        assert batch_size == 2
        assert show_progress_bar is False
        return [0.3, 0.7]


@pytest.mark.unit
def test_bge_reranker_orders_compute_score_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reranker = BgeReranker(batch_size=2)

    def fake_ensure_model() -> _ComputeScoreModel:
        return _ComputeScoreModel()

    monkeypatch.setattr(reranker, "_ensure_model", fake_ensure_model)

    result = reranker.rerank(
        query="query",
        candidates=[
            RerankCandidate(chunk_id="a", text="least relevant"),
            RerankCandidate(chunk_id="b", text="most relevant"),
            RerankCandidate(chunk_id="c", text="middle"),
        ],
        top_k=2,
    )

    assert result.indices == [1, 2]
    assert result.scores == [0.9, 0.4]
    assert result.usage.provider == "local"


@pytest.mark.unit
def test_bge_reranker_supports_predict_models() -> None:
    reranker = BgeReranker(batch_size=2)

    assert reranker._score(_PredictModel(), [("query", "alpha"), ("query", "beta")]) == [0.3, 0.7]


@pytest.mark.unit
def test_bge_reranker_rejects_unknown_model_api() -> None:
    with pytest.raises(RerankerError, match="neither compute_score nor predict"):
        BgeReranker()._score(object(), [("query", "text")])
