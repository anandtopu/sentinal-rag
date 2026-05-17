"""End-to-end RAG pipeline as a stages package.

Public surface:

- ``Orchestrator`` — coordinates the per-request pipeline.
- ``QueryContext`` — mutable bag passed between stages.
- ``RetrievalConfig`` / ``GenerationConfig`` / ``QueryOptions`` — request configs.
- ``QueryResult`` / ``CitationOut`` — response shapes.
- ``RetrievalClient`` / ``InProcessRetrievalClient`` — the seam R4 plugs the
  HTTP impl into.
"""

from __future__ import annotations

from app.services.rag.client import InProcessRetrievalClient, RetrievalClient
from app.services.rag.orchestrator import Orchestrator
from app.services.rag.types import (
    CitationOut,
    GenerationConfig,
    QueryContext,
    QueryOptions,
    QueryResult,
    RetrievalConfig,
)

__all__ = [
    "CitationOut",
    "GenerationConfig",
    "InProcessRetrievalClient",
    "Orchestrator",
    "QueryContext",
    "QueryOptions",
    "QueryResult",
    "RetrievalClient",
    "RetrievalConfig",
]
