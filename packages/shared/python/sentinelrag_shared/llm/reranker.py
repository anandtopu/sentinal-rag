from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from sentinelrag_shared.llm.types import UsageRecord


class RerankerError(Exception):
    """Raised when reranking fails irrecoverably."""


@dataclass(slots=True)
class RerankCandidate:
    chunk_id: str
    text: str


@dataclass(slots=True)
class RerankResult:
    indices: list[int]
    scores: list[float]
    model_name: str
    usage: UsageRecord = field(default_factory=UsageRecord)


class Reranker(Protocol):
    model_name: str

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int,
    ) -> RerankResult: ...


class NoOpReranker:
    """Pass-through reranker that preserves input order."""

    model_name = "noop"

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int,
    ) -> RerankResult:
        del query
        n = min(max(top_k, 0), len(candidates))
        return RerankResult(
            indices=list(range(n)),
            scores=[1.0 - (i * 0.01) for i in range(n)],
            model_name=self.model_name,
            usage=UsageRecord(
                usage_type="rerank",
                provider="local",
                model_name=self.model_name,
                total_cost_usd=Decimal("0"),
            ),
        )


_bge_lock = threading.Lock()
_bge_model: Any | None = None
_bge_model_name: str | None = None


class BgeReranker:
    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
        max_length: int = 512,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.max_length = max_length
        self.batch_size = batch_size

    def _ensure_model(self) -> Any:
        global _bge_model, _bge_model_name

        if _bge_model is not None and _bge_model_name == self.model_name:
            return _bge_model

        with _bge_lock:
            if _bge_model is not None and _bge_model_name == self.model_name:
                return _bge_model

            try:
                from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
            except ImportError:
                FlagReranker = None  # type: ignore[assignment]

            if FlagReranker is not None:
                try:
                    _bge_model = FlagReranker(self.model_name, use_fp16=self.use_fp16)
                    _bge_model_name = self.model_name
                    return _bge_model
                except Exception as exc:
                    raise RerankerError(
                        f"FlagReranker failed to load {self.model_name!r}: {exc}"
                    ) from exc

            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

                _bge_model = CrossEncoder(self.model_name, max_length=self.max_length)
                _bge_model_name = self.model_name
                return _bge_model
            except Exception as exc:
                raise RerankerError(
                    f"Neither FlagEmbedding nor sentence-transformers could load {self.model_name!r}: {exc}"
                ) from exc

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int,
    ) -> RerankResult:
        if not candidates:
            return RerankResult(
                indices=[],
                scores=[],
                model_name=self.model_name,
                usage=UsageRecord(
                    usage_type="rerank",
                    provider="local",
                    model_name=self.model_name,
                    total_cost_usd=Decimal("0"),
                ),
            )

        model = self._ensure_model()
        pairs = [(query, c.text) for c in candidates]
        start = time.perf_counter()
        scores = self._score(model, pairs)
        latency_ms = int((time.perf_counter() - start) * 1000)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[: max(top_k, 0)]

        return RerankResult(
            indices=[i for i, _ in ranked],
            scores=[float(s) for _, s in ranked],
            model_name=self.model_name,
            usage=UsageRecord(
                usage_type="rerank",
                provider="local",
                model_name=self.model_name,
                total_tokens=len(candidates),
                total_cost_usd=Decimal("0"),
                latency_ms=latency_ms,
            ),
        )

    def _score(self, model: Any, pairs: list[tuple[str, str]]) -> list[float]:
        if hasattr(model, "compute_score"):
            raw = model.compute_score(
                pairs,
                normalize=True,
                batch_size=self.batch_size,
            )
            if isinstance(raw, list):
                return [float(s) for s in raw]
            return [float(raw)]

        if hasattr(model, "predict"):
            raw = model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
            return [float(s) for s in raw]

        raise RerankerError("Loaded model has neither compute_score nor predict")
