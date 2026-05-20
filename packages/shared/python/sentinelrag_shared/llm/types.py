from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: Any | None = None
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    usage: dict[str, int] | None = None
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class GeneratorResult:
    text: str
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RerankResult:
    scores: list[float]
    model: str | None = None


ModelProvider = Literal["ollama", "openai", "azure", "local"]
