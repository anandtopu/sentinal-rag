"""SemanticChunker — paragraph/sentence-aware chunking.

Strategy:
    1. Concatenate elements into a stream of paragraphs (preserving section
       titles and page numbers from the first element of each paragraph).
    2. Walk paragraphs, accumulating into a chunk until adding the next
       paragraph would exceed ``target_tokens``.
    3. If a single paragraph exceeds ``target_tokens``, split on sentence
       boundaries (``. ! ?``) preserving up to ``overlap_tokens`` of overlap
       between adjacent chunks.

This is "semantic" in the sense that paragraph + sentence boundaries are
respected, not in the embedding-similarity sense (that variant is
implemented by community libraries like ``semantic-text-splitter`` and
will be added behind a feature flag in a later phase if quality demands).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sentinelrag_shared.chunking.base import Chunk, Chunker, ChunkingStrategy, count_tokens
from sentinelrag_shared.parsing.elements import ParsedElement

# Tokens contributed by joining "\n\n" between paragraphs. Approximate; we
# don't tokenize the join string each time.
_JOIN_TOKEN_COST = 1

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class SemanticChunker(Chunker):
    strategy = ChunkingStrategy.SEMANTIC

    def __init__(
        self,
        *,
        target_tokens: int = 512,
        overlap_tokens: int = 64,
        min_chunk_tokens: int = 32,
    ) -> None:
        if overlap_tokens >= target_tokens:
            msg = "overlap_tokens must be smaller than target_tokens"
            raise ValueError(msg)
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens

    def chunk(self, elements: Sequence[ParsedElement]) -> list[Chunk]:
        out: list[Chunk] = []
        buffer: list[str] = []
        buffer_tokens = 0
        anchor_page: int | None = None
        anchor_section: str | None = None

        def emit() -> None:
            nonlocal buffer, buffer_tokens, anchor_page, anchor_section
            if not buffer:
                return
            text = "\n\n".join(buffer).strip()
            if not text:
                buffer, buffer_tokens, anchor_page, anchor_section = [], 0, None, None
                return
            tokens = count_tokens(text)
            if tokens < self.min_chunk_tokens and out:
                # Merge with previous chunk if the trailing piece is too small.
                prev = out[-1]
                merged_text = f"{prev.text}\n\n{text}"
                out[-1] = Chunk(
                    text=merged_text,
                    chunk_index=prev.chunk_index,
                    token_count=count_tokens(merged_text),
                    page_number=prev.page_number,
                    section_title=prev.section_title,
                    table_html=prev.table_html,
                    metadata=prev.metadata,
                )
            else:
                out.append(
                    Chunk(
                        text=text,
                        chunk_index=len(out),
                        token_count=tokens,
                        page_number=anchor_page,
                        section_title=anchor_section,
                    )
                )
            buffer, buffer_tokens, anchor_page, anchor_section = [], 0, None, None

        for elem in elements:
            if not elem.is_chunkable():
                continue
            text = elem.text.strip()
            if not text:
                continue
            tokens = count_tokens(text)

            if tokens > self.target_tokens:
                # Single oversized paragraph — emit current buffer first,
                # then sentence-split this paragraph.
                emit()
                for sub_chunk in self._split_long_text(text, elem):
                    out.append(
                        Chunk(
                            text=sub_chunk,
                            chunk_index=len(out),
                            token_count=count_tokens(sub_chunk),
                            page_number=elem.page_number,
                            section_title=elem.section_title,
                        )
                    )
                continue

            # Would adding this element overflow the budget? Emit and reset.
            if buffer_tokens + _JOIN_TOKEN_COST + tokens > self.target_tokens:
                emit()

            if not buffer:
                anchor_page = elem.page_number
                anchor_section = elem.section_title
            buffer.append(text)
            buffer_tokens += tokens + (_JOIN_TOKEN_COST if len(buffer) > 1 else 0)

        emit()
        return out

    def _split_long_text(self, text: str, elem: ParsedElement) -> list[str]:
        """Sentence-split with ``overlap_tokens`` of trailing overlap.

        When a single "sentence" itself exceeds ``target_tokens`` (e.g. a
        paragraph with no terminal punctuation, code blocks, or one long
        run-on), fall back to a fixed-size token-window split as a backstop.
        """
        del elem  # unused; caller anchors page/section
        sentences = _SENTENCE_BOUNDARY.split(text)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        def _flush() -> None:
            nonlocal current, current_tokens
            if not current:
                return
            chunks.append(" ".join(current).strip())
            overlap_tail: list[str] = []
            tail_tokens = 0
            for prev in reversed(current):
                p_tokens = count_tokens(prev)
                if tail_tokens + p_tokens > self.overlap_tokens:
                    break
                overlap_tail.insert(0, prev)
                tail_tokens += p_tokens
            current = overlap_tail.copy()
            current_tokens = tail_tokens

        for sentence in sentences:
            if not sentence.strip():
                continue
            stoks = count_tokens(sentence)

            # Backstop: a single "sentence" is bigger than our budget.
            # Token-window-split it directly; preserves overlap.
            if stoks > self.target_tokens:
                _flush()
                for window in self._token_window_split(sentence):
                    chunks.append(window)
                continue

            if current_tokens + stoks > self.target_tokens and current:
                _flush()
            current.append(sentence)
            current_tokens += stoks

        _flush()
        return [c for c in chunks if c]

    def _token_window_split(self, text: str) -> list[str]:
        """Fixed-size token-window split with overlap. Backstop for run-ons."""
        import tiktoken  # noqa: PLC0415

        enc = tiktoken.get_encoding("cl100k_base")
        ids = enc.encode(text, disallowed_special=())
        out: list[str] = []
        step = max(1, self.target_tokens - self.overlap_tokens)
        for start in range(0, len(ids), step):
            window = ids[start : start + self.target_tokens]
            out.append(enc.decode(window))
            if start + self.target_tokens >= len(ids):
                break
        return out
