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

    @property
    def usagetype(self) -> str | None:
        return self.usage_type

    @property
    def modelname(self) -> str | None:
        return self.model_name

    @property
    def inputtokens(self) -> int:
        return self.input_tokens

    @property
    def outputtokens(self) -> int:
        return self.output_tokens

    @property
    def totaltokens(self) -> int:
        return self.total_tokens

    @property
    def totalcostusd(self) -> Decimal | None:
        return self.total_cost_usd

    @property
    def latencyms(self) -> int | None:
        return self.latency_ms


@dataclass(slots=True)
class EmbeddingResult:
    embeddings: list[list[float]]
    model_name: str | None = None
    usage: UsageRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    dimensions: int | None = None

    @property
    def vectors(self) -> list[list[float]]:
        return self.embeddings

    @property
    def modelname(self) -> str | None:
        return self.model_name


@dataclass(slots=True)
class RerankResult:
    indices: list[int] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    model_name: str | None = None
    usage: UsageRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def modelname(self) -> str | None:
        return self.model_name


@dataclass(slots=True)
class GenerateResult:
    text: str
    finish_reason: str | None = None
    model_name: str | None = None
    usage: UsageRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def finishreason(self) -> str | None:
        return self.finish_reason

    @property
    def modelname(self) -> str | None:
        return self.model_name
