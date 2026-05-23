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

    def __init__(
        self,
        usage_type: str | None = None,
        provider: str | None = None,
        model_name: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        total_cost_usd: Decimal | None = None,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        usagetype: str | None = None,
        modelname: str | None = None,
        inputtokens: int | None = None,
        outputtokens: int | None = None,
        totaltokens: int | None = None,
        totalcostusd: Decimal | None = None,
        latencyms: int | None = None,
    ) -> None:
        self.usage_type = usage_type if usage_type is not None else usagetype
        self.provider = provider
        self.model_name = model_name if model_name is not None else modelname
        self.input_tokens = input_tokens if inputtokens is None else inputtokens
        self.output_tokens = output_tokens if outputtokens is None else outputtokens
        self.total_tokens = total_tokens if totaltokens is None else totaltokens
        self.total_cost_usd = (
            total_cost_usd if totalcostusd is None else totalcostusd
        )
        self.latency_ms = latency_ms if latencyms is None else latencyms
        self.metadata = {} if metadata is None else metadata

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


@dataclass(slots=True, init=False)
class EmbeddingResult:
    embeddings: list[list[float]]
    model_name: str | None
    usage: UsageRecord | None
    metadata: dict[str, Any]
    dimensions: int | None

    def __init__(
        self,
        embeddings: list[list[float]] | None = None,
        model_name: str | None = None,
        usage: UsageRecord | None = None,
        metadata: dict[str, Any] | None = None,
        dimensions: int | None = None,
        *,
        vectors: list[list[float]] | None = None,
        modelname: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self.embeddings = embeddings if embeddings is not None else (vectors or [])
        self.model_name = model_name if model_name is not None else modelname
        self.usage = usage
        self.metadata = {} if metadata is None else metadata
        self.dimensions = dimensions if dimensions is not None else dimension

    @property
    def vectors(self) -> list[list[float]]:
        return self.embeddings

    @property
    def modelname(self) -> str | None:
        return self.model_name

    @property
    def dimension(self) -> int | None:
        return self.dimensions


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
