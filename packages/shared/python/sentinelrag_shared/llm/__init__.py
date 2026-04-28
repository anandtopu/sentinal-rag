"""LLM gateway: unified embeddings, completions, and reranking via LiteLLM (ADR-0005).

All LLM calls in SentinelRAG go through this layer, NOT the provider SDK
directly. The adapter layer handles routing, fallbacks, token counting, and
cost computation.
"""

from sentinelrag_shared.llm.embedder import (
    EMBEDDER_DIMENSIONS,
    Embedder,
    EmbedderError,
    LiteLLMEmbedder,
)
from sentinelrag_shared.llm.generator import (
    Generator,
    GeneratorError,
    LiteLLMGenerator,
)
from sentinelrag_shared.llm.reranker import (
    BgeReranker,
    NoOpReranker,
    RerankCandidate,
    Reranker,
    RerankerError,
)
from sentinelrag_shared.llm.types import (
    EmbeddingResult,
    GenerationResult,
    RerankResult,
    UsageRecord,
)

__all__ = [
    "EMBEDDER_DIMENSIONS",
    "BgeReranker",
    "Embedder",
    "EmbedderError",
    "EmbeddingResult",
    "GenerationResult",
    "Generator",
    "GeneratorError",
    "LiteLLMEmbedder",
    "LiteLLMGenerator",
    "NoOpReranker",
    "RerankCandidate",
    "RerankResult",
    "Reranker",
    "RerankerError",
    "UsageRecord",
]
