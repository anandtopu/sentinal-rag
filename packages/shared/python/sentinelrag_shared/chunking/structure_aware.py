"""StructureAwareChunker — respects ParsedElement boundaries.

Rules:
    - Tables are NEVER split. A table that exceeds ``target_tokens`` is
      emitted as its own oversize chunk. Mid-table splits destroy retrievable
      semantics, which is the whole point of having structure-aware chunking.
    - Titles / headings always start a new chunk and are kept with the
      following content (they become the chunk's ``section_title``).
    - List items are grouped with neighboring list items until the budget
      is exceeded.
    - Narrative paragraphs are filled greedily within ``target_tokens``.

This is the recommended strategy for technical documentation, runbooks,
and structured PDFs.
"""

from __future__ import annotations

from collections.abc import Sequence

from sentinelrag_shared.chunking.base import Chunk, Chunker, ChunkingStrategy, count_tokens
from sentinelrag_shared.parsing.elements import ElementType, ParsedElement


class StructureAwareChunker(Chunker):
    strategy = ChunkingStrategy.STRUCTURE_AWARE

    def __init__(
        self,
        *,
        target_tokens: int = 512,
        overlap_tokens: int = 0,  # structure-aware doesn't use overlap by default
    ) -> None:
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, elements: Sequence[ParsedElement]) -> list[Chunk]:
        out: list[Chunk] = []
        buffer: list[ParsedElement] = []
        buffer_tokens = 0
        active_section: str | None = None

        def emit() -> None:
            nonlocal buffer, buffer_tokens
            if not buffer:
                return
            text_parts = [
                e.table_html or e.text
                for e in buffer
                if (e.table_html or e.text.strip())
            ]
            text = "\n\n".join(text_parts).strip()
            if not text:
                buffer, buffer_tokens = [], 0
                return
            anchor = buffer[0]
            out.append(
                Chunk(
                    text=text,
                    chunk_index=len(out),
                    token_count=count_tokens(text),
                    page_number=anchor.page_number,
                    section_title=active_section or anchor.section_title,
                    table_html=anchor.table_html if len(buffer) == 1 else None,
                )
            )
            buffer, buffer_tokens = [], 0

        for elem in elements:
            if not elem.is_chunkable():
                continue

            # Title/heading → close the current chunk and start a new section.
            if elem.element_type in {ElementType.TITLE, ElementType.HEADING}:
                emit()
                active_section = elem.text.strip() or active_section
                # We don't add the heading itself as a chunk — its content lives
                # in the section_title metadata of subsequent chunks.
                continue

            tokens = count_tokens(elem.table_html or elem.text)

            # Tables: never split, never combine with other content.
            if elem.element_type == ElementType.TABLE:
                emit()
                buffer = [elem]
                buffer_tokens = tokens
                emit()
                continue

            # Would adding this element overflow the budget?
            if buffer_tokens + tokens > self.target_tokens and buffer:
                emit()

            buffer.append(elem)
            buffer_tokens += tokens

        emit()
        return out
