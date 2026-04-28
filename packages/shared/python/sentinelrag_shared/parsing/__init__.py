"""Document parsers (shared library; consumed by ingestion-service and temporal-worker).

The ``Parser`` protocol abstracts over per-format parsing. ``UnstructuredParser``
dispatches to the ``unstructured`` library for PDF/DOCX/HTML/MD/CSV/EML/PPTX/XLSX
(ADR-0013).
"""

from sentinelrag_shared.parsing.elements import ElementType, ParsedElement
from sentinelrag_shared.parsing.parser import Parser, ParserError
from sentinelrag_shared.parsing.unstructured_parser import UnstructuredParser

__all__ = [
    "ElementType",
    "ParsedElement",
    "Parser",
    "ParserError",
    "UnstructuredParser",
]
