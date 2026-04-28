"""ParsedElement — the unit of parser output, decoupled from unstructured's API.

By round-tripping through this internal type, the chunking layer is
ignorant of which parser produced it; swapping ``UnstructuredParser`` for
``LlamaParseParser`` later is a one-file change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ElementType(StrEnum):
    """Coarse type classification used by structure-aware chunking."""

    TITLE = "title"
    HEADING = "heading"
    NARRATIVE_TEXT = "narrative_text"
    LIST_ITEM = "list_item"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"
    PAGE_BREAK = "page_break"
    HEADER = "header"
    FOOTER = "footer"
    UNCATEGORIZED = "uncategorized"


@dataclass(slots=True)
class ParsedElement:
    """One semantic unit extracted from a document."""

    text: str
    element_type: ElementType = ElementType.UNCATEGORIZED
    page_number: int | None = None
    section_title: str | None = None
    table_html: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_chunkable(self) -> bool:
        """Whether this element should be eligible for vector embedding.

        Headers/footers, page breaks, and bare images are excluded — they're
        navigational, not content.
        """
        return self.element_type not in {
            ElementType.HEADER,
            ElementType.FOOTER,
            ElementType.PAGE_BREAK,
            ElementType.IMAGE,
        } and bool(self.text.strip())
