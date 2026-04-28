"""Chunking strategies (shared library; consumed by ingestion-service and temporal-worker).

Three strategies ship in v1:
    - SemanticChunker — paragraph/sentence-aware, fills to a token budget.
    - SlidingWindowChunker — fixed-size windows with overlap, ignores semantics.
    - StructureAwareChunker — respects ParsedElement boundaries (never splits
      tables, keeps headings with following content).

All implement the Chunker protocol and produce :class:`Chunk` objects.
"""

from typing import Any

from sentinelrag_shared.chunking.base import Chunk, Chunker, ChunkingStrategy
from sentinelrag_shared.chunking.semantic import SemanticChunker
from sentinelrag_shared.chunking.sliding_window import SlidingWindowChunker
from sentinelrag_shared.chunking.structure_aware import StructureAwareChunker

__all__ = [
    "Chunk",
    "Chunker",
    "ChunkingStrategy",
    "SemanticChunker",
    "SlidingWindowChunker",
    "StructureAwareChunker",
    "get_chunker",
]


def get_chunker(strategy: ChunkingStrategy, **kwargs: Any) -> Chunker:
    """Factory mapping ChunkingStrategy → concrete Chunker instance."""
    match strategy:
        case ChunkingStrategy.SEMANTIC:
            return SemanticChunker(**kwargs)
        case ChunkingStrategy.SLIDING_WINDOW:
            return SlidingWindowChunker(**kwargs)
        case ChunkingStrategy.STRUCTURE_AWARE:
            return StructureAwareChunker(**kwargs)
