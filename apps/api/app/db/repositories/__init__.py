"""Repository layer."""

from app.db.repositories.answer_citations import AnswerCitationRepository
from app.db.repositories.base import BaseRepository
from app.db.repositories.budgets import TenantBudgetRepository
from app.db.repositories.collections import CollectionRepository
from app.db.repositories.documents import (
    ChunkEmbeddingRepository,
    DocumentChunkRepository,
    DocumentRepository,
    DocumentVersionRepository,
)
from app.db.repositories.generated_answers import GeneratedAnswerRepository
from app.db.repositories.ingestion_jobs import IngestionJobRepository
from app.db.repositories.permissions import PermissionRepository
from app.db.repositories.query_sessions import QuerySessionRepository
from app.db.repositories.retrieval_results import RetrievalResultRepository
from app.db.repositories.roles import RoleRepository
from app.db.repositories.tenants import TenantRepository
from app.db.repositories.usage_records import UsageRecordRepository
from app.db.repositories.users import UserRepository

__all__ = [
    "AnswerCitationRepository",
    "BaseRepository",
    "ChunkEmbeddingRepository",
    "CollectionRepository",
    "DocumentChunkRepository",
    "DocumentRepository",
    "DocumentVersionRepository",
    "GeneratedAnswerRepository",
    "IngestionJobRepository",
    "PermissionRepository",
    "QuerySessionRepository",
    "RetrievalResultRepository",
    "RoleRepository",
    "TenantBudgetRepository",
    "TenantRepository",
    "UsageRecordRepository",
    "UserRepository",
]
