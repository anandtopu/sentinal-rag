"""Per-stage modules of the RAG pipeline.

Each stage operates on a shared ``QueryContext``. Stages are independently
unit-testable; integration tests cover end-to-end flow via the orchestrator.
"""

from __future__ import annotations

from app.services.rag.stages.audit import AuditStage
from app.services.rag.stages.budget import BudgetStage
from app.services.rag.stages.context_assembly import ContextAssemblyStage
from app.services.rag.stages.generation import GenerationStage
from app.services.rag.stages.grounding import GroundingStage
from app.services.rag.stages.persistence import PersistenceStage
from app.services.rag.stages.prompt import PromptStage
from app.services.rag.stages.rerank import RerankStage
from app.services.rag.stages.retrieval import RetrievalStage as RetrievalRunStage
from app.services.rag.stages.session import SessionStage

__all__ = [
    "AuditStage",
    "BudgetStage",
    "ContextAssemblyStage",
    "GenerationStage",
    "GroundingStage",
    "PersistenceStage",
    "PromptStage",
    "RerankStage",
    "RetrievalRunStage",
    "SessionStage",
]
