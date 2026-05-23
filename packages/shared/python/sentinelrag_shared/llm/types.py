from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class UsageRecord:
    usage_type: str | None = None
    provider: str | None = None
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal | None = None
    latency_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, init=False)
class EmbeddingResult:
    vectors: list[list[float]]
    model_name: str | None
    dimensions: int | None
    usage: UsageRecord | None
    metadata: dict[str, Any]

    def __init__(
        self,
        vectors: list[list[float]],
        model_name: str | None = None,
        dimensions: int | None = None,
        dimension: int | None = None,
        usage: UsageRecord | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.vectors = vectors
        self.model_name = model_name
        self.dimensions = dimensions if dimensions is not None else dimension
        self.usage = usage
        self.metadata = metadata or {}

    @property
    def embeddings(self) -> list[list[float]]:
        return self.vectors

    @property
    def dimension(self) -> int | None:
        return self.dimensions


@dataclass(slots=True)
class RerankResult:
    indices: list[int]
    scores: list[float]
    model_name: str | None = None
    usage: UsageRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GenerateResult:
    text: str
    finish_reason: str | None = None
    model_name: str | None = None
    usage: UsageRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
