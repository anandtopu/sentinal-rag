"""Parser protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sentinelrag_shared.parsing.elements import ParsedElement


class ParserError(Exception):
    """Raised when parsing fails irrecoverably for a given blob."""


class Parser(Protocol):
    """Parse a binary blob into an ordered sequence of ParsedElement."""

    def parse(
        self,
        *,
        blob: bytes,
        mime_type: str,
        filename: str | None = None,
    ) -> Sequence[ParsedElement]:
        """Return parsed elements in document order.

        Args:
            blob: Raw bytes of the source document.
            mime_type: e.g. ``application/pdf``, ``text/html``, ``text/plain``.
            filename: Optional original filename; some parsers infer format from extension.
        """
        ...
