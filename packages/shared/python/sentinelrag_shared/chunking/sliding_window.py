"""SlidingWindowChunker — fixed-size token windows with overlap.

Fastest and most deterministic strategy. Useful for benchmarks and as a
baseline against which the semantic / structure-aware chunkers are compared.
Doesn't respect any document structure — splits mid-sentence if needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import tiktoken

from sentinelrag_shared.chunking.base import Chunk, Chunker, ChunkingStrategy, count_tokens
from sentinelrag_shared.parsing.elements import ParsedElement

_ENCODING = tiktoken.get_encoding("cl100k_base")


class SlidingWindowChunker(Chunker):
    strategy = ChunkingStrategy.SLIDING_WINDOW

    def __init__(
        self,
        *,
        target_tokens: int = 512,
        overlap_tokens: int = 64,
    ) -> None:
        if overlap_tokens >= target_tokens:
            msg = "overlap_tokens must be smaller than target_tokens"
            raise ValueError(msg)
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, elements: Sequence[ParsedElement]) -> list[Chunk]:
        # Concatenate chunkable elements into one stream, remembering page/
        # section anchors at fixed character offsets so we can attribute
        # each chunk back to a page.
        joined_pieces: list[str] = []
        anchors: list[tuple[int, ParsedElement]] = []  # (char_offset, source_elem)
        cursor = 0
        for elem in elements:
            if not elem.is_chunkable():
                continue
            text = elem.text.strip()
            if not text:
                continue
            anchors.append((cursor, elem))
            joined_pieces.append(text)
            cursor += len(text) + 2  # account for the "\n\n" join

        full_text = "\n\n".join(joined_pieces)
        if not full_text:
            return []

        token_ids = _ENCODING.encode(full_text, disallowed_special=())
        out: list[Chunk] = []
        step = self.target_tokens - self.overlap_tokens
        for window_start in range(0, len(token_ids), step):
            window = token_ids[window_start : window_start + self.target_tokens]
            text = _ENCODING.decode(window)
            char_offset = len(_ENCODING.decode(token_ids[:window_start]))
            anchor = self._anchor_at(char_offset, anchors)
            out.append(
                Chunk(
                    text=text,
                    chunk_index=len(out),
                    token_count=count_tokens(text),
                    page_number=anchor.page_number if anchor else None,
                    section_title=anchor.section_title if anchor else None,
                )
            )
            if window_start + self.target_tokens >= len(token_ids):
                break
        return out

    @staticmethod
    def _anchor_at(
        char_offset: int,
        anchors: list[tuple[int, ParsedElement]],
    ) -> ParsedElement | None:
        """Return the ParsedElement whose anchor most recently precedes char_offset."""
        last: ParsedElement | None = None
        for offset, elem in anchors:
            if offset > char_offset:
                break
            last = elem
        return last
