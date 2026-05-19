from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from sentence_transformers import (
    CrossEncoder as SentenceTransformersCrossEncoder,  # pyright: ignore[reportMissingImports]
)

from sentinelrag_shared.llm.types import RerankResult


class _CrossEncoderLike(Protocol):
    def predict(self, sentences: Sequence[tuple[str, str]]) -> Sequence[float]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]: ...


class SentenceTransformerReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        self.model_name = model_name
        self._model: _CrossEncoderLike | None = None

    def _get_model(self) -> _CrossEncoderLike:
        if self._model is None:
            try:
                self._model = cast(
                    _CrossEncoderLike,
                    SentenceTransformersCrossEncoder(self.model_name),
                )
            except Exception as exc:
                raise RuntimeError(
                    "sentence-transformers is required at runtime for "
                    "SentenceTransformerReranker, but it is not available in this "
                    "environment."
                ) from exc
        return self._model

    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        model = self._get_model()
        pairs = [(query, document) for document in documents]
        scores = model.predict(pairs)

        results = [
            RerankResult(document=document, score=float(score), index=index)
            for index, (document, score) in enumerate(zip(documents, scores, strict=False))
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return results
