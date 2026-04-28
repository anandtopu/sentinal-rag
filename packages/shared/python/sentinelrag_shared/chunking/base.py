"""Chunker protocol + Chunk dataclass + token counting.

Token counting uses ``tiktoken`` with the ``cl100k_base`` encoding (used by
GPT-3.5/4 and roughly compatible with most modern tokenizers). Chunkers
target a token budget rather than a character budget so results are
embedder-agnostic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import tiktoken

from sentinelrag_shared.parsing.elements import ParsedElement

# Single shared encoding instance — tiktoken's encodings are expensive to load.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text, disallowed_special=()))


class ChunkingStrategy(StrEnum):
    SEMANTIC = "semantic"
    SLIDING_WINDOW = "sliding_window"
    STRUCTURE_AWARE = "structure_aware"


@dataclass(slots=True)
class Chunk:
    """One unit ready for embedding + indexing."""

    text: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    section_title: str | None = None
    table_html: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Chunker(Protocol):
    """Convert ParsedElements into Chunks.

    Implementations are stateless and reentrant.
    """

    strategy: ChunkingStrategy
    target_tokens: int
    overlap_tokens: int

    def chunk(self, elements: Sequence[ParsedElement]) -> list[Chunk]: ...
