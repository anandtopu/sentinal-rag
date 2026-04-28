"""Shared result + usage types for the LLM gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(slots=True)
class UsageRecord:
    """Token + cost accounting for a single LLM call.

    Mirrors the columns of the ``usage_records`` table; the cost service
    persists these via repository calls.
    """

    usage_type: str  # 'embedding' | 'completion' | 'rerank' | 'evaluation'
    provider: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    unit_cost_usd: Decimal | None = None
    total_cost_usd: Decimal | None = None
    latency_ms: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class EmbeddingResult:
    """Result of a single embedder call (one or many vectors)."""

    vectors: list[list[float]]
    model_name: str
    dimension: int
    usage: UsageRecord


@dataclass(slots=True)
class GenerationResult:
    text: str
    finish_reason: str | None
    usage: UsageRecord


@dataclass(slots=True)
class RerankResult:
    indices: list[int]            # original positions of reranked candidates
    scores: list[float]           # parallel to ``indices``
    model_name: str
    usage: UsageRecord
