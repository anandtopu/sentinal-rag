from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def _json_dict() -> dict[str, JsonValue]:
    return {}


@dataclass(slots=True)
class UsageRecord:
    usage_type: str = "llm"
    provider: str | None = None
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal | None = None
    latency_ms: int | None = None
    extra: dict[str, JsonValue] = field(default_factory=_json_dict)


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model_name: str
    dimension: int
    provider: str | None = None
    usage: UsageRecord = field(default_factory=UsageRecord)


@dataclass(slots=True)
class GenerationResult:
    text: str
    model_name: str
    provider: str | None = None
    finish_reason: str | None = None
    usage: UsageRecord = field(default_factory=UsageRecord)
    raw_response: dict[str, JsonValue] = field(default_factory=_json_dict)


@dataclass(slots=True)
class RerankResult:
    document: str
    score: float
    index: int
    metadata: dict[str, JsonValue] = field(default_factory=_json_dict)
