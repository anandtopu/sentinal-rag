"""UnstructuredParser — wraps ``unstructured.partition.auto.partition``.

Maps unstructured's Element classes to our :class:`ElementType` so the
chunking layer doesn't depend on the unstructured API. Per ADR-0013, this
is the only parser shipping in v1.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from typing import Any

from sentinelrag_shared.parsing.elements import ElementType, ParsedElement
from sentinelrag_shared.parsing.parser import Parser, ParserError

# Mapping from unstructured element class names → our internal ElementType.
# Class names are stable across unstructured releases; using class names
# (not isinstance) lets us avoid the heavy import at module load.
_ELEMENT_TYPE_MAP: dict[str, ElementType] = {
    "Title": ElementType.TITLE,
    "Header": ElementType.HEADER,
    "Footer": ElementType.FOOTER,
    "NarrativeText": ElementType.NARRATIVE_TEXT,
    "Text": ElementType.NARRATIVE_TEXT,
    "ListItem": ElementType.LIST_ITEM,
    "Table": ElementType.TABLE,
    "Image": ElementType.IMAGE,
    "Formula": ElementType.FORMULA,
    "PageBreak": ElementType.PAGE_BREAK,
    "Address": ElementType.NARRATIVE_TEXT,
    "EmailAddress": ElementType.NARRATIVE_TEXT,
    "FigureCaption": ElementType.NARRATIVE_TEXT,
}


class UnstructuredParser(Parser):
    """Parser using the ``unstructured`` library."""

    def __init__(self, *, strategy: str = "fast") -> None:
        """
        Args:
            strategy: ``fast`` (text-only PDF, no OCR — quickest)
                      ``hi_res`` (uses layout model + OCR — slower, better tables)
                      ``ocr_only`` (forces OCR even on text-PDFs)
                      ``auto`` (detect)
        """
        self.strategy = strategy

    def parse(
        self,
        *,
        blob: bytes,
        mime_type: str,
        filename: str | None = None,
    ) -> Sequence[ParsedElement]:
        # Lazy import — ``unstructured`` is heavy and only the ingestion-service
        # has it as a runtime dep. Importing at module level would slow down
        # other consumers of the package.
        try:
            from unstructured.partition.auto import partition  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "unstructured is not installed. The parser is available only "
                "in apps/ingestion-service."
            )
            raise ParserError(msg) from exc

        try:
            elements = partition(
                file=io.BytesIO(blob),
                content_type=mime_type,
                metadata_filename=filename,
                strategy=self.strategy,
            )
        except Exception as exc:
            raise ParserError(f"unstructured.partition failed: {exc}") from exc

        return [self._convert(elem) for elem in elements]

    @staticmethod
    def _convert(elem: Any) -> ParsedElement:
        cls_name = type(elem).__name__
        element_type = _ELEMENT_TYPE_MAP.get(cls_name, ElementType.UNCATEGORIZED)

        meta = elem.metadata.to_dict() if elem.metadata else {}
        page_number = meta.get("page_number")
        section_title = meta.get("section") or meta.get("category_depth")
        table_html = meta.get("text_as_html") if element_type == ElementType.TABLE else None

        # Drop heavy nested fields that don't survive serialization cleanly.
        for k in ("orig_elements", "coordinates", "languages"):
            meta.pop(k, None)

        return ParsedElement(
            text=str(elem.text or "").strip(),
            element_type=element_type,
            page_number=page_number,
            section_title=section_title if isinstance(section_title, str) else None,
            table_html=table_html,
            metadata=meta,
        )
