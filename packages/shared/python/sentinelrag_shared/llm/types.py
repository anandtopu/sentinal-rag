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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddingResult:
    embeddings: list[list[float]]
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
