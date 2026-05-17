"""Shared FastAPI dependencies that build singleton-style resources from app state.

The Temporal client, ObjectStorage adapter, and Reranker are constructed once
at startup (see ``app/lifecycle.py``) and stored on ``request.app.state``.
These dependency factories pull them out for routes that need them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sentinelrag_shared.errors import TemporalUnavailableError
from sentinelrag_shared.llm import LiteLLMEmbedder, Reranker
from sentinelrag_shared.object_storage import ObjectStorage
from temporalio.client import Client as TemporalClient

from app.services.budget_reservation import BudgetReservationService
from app.services.idempotency import IdempotencyService
from app.services.rag.client import RetrievalClient


def get_object_storage(request: Request) -> ObjectStorage:
    storage = getattr(request.app.state, "object_storage", None)
    if storage is None:
        msg = "Object storage not configured."
        raise RuntimeError(msg)
    return storage


def get_audit_storage(request: Request) -> ObjectStorage:
    storage = getattr(request.app.state, "audit_storage", None)
    if storage is None:
        msg = "Audit object storage not configured."
        raise RuntimeError(msg)
    return storage


def get_temporal_client(request: Request) -> TemporalClient:
    client = getattr(request.app.state, "temporal_client", None)
    if client is None:
        raise TemporalUnavailableError("Temporal client not configured.")
    return client


def get_reranker(request: Request) -> Reranker:
    reranker = getattr(request.app.state, "reranker", None)
    if reranker is None:
        msg = "Reranker not configured."
        raise RuntimeError(msg)
    return reranker


def get_redis(request: Request) -> Redis | None:
    """May return None — both idempotency and the reservation gate
    degrade to no-op when Redis is unreachable so the API stays up
    in local dev / partial outages.
    """
    return getattr(request.app.state, "redis", None)


def get_idempotency_service(request: Request) -> IdempotencyService:
    return IdempotencyService(get_redis(request))


def get_budget_reservation_service(request: Request) -> BudgetReservationService:
    return BudgetReservationService(get_redis(request))


def get_retrieval_client(request: Request) -> RetrievalClient | None:
    """May return None — the orchestrator's fallback constructs a
    per-request ``InProcessRetrievalClient`` against the request-scoped
    SQLAlchemy session, which is the right lifetime for in-process mode.
    """
    return getattr(request.app.state, "retrieval_client", None)


def get_embedder(request: Request) -> LiteLLMEmbedder:
    """Process-singleton embedder hoisted in lifecycle (R3.S6)."""
    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None:
        msg = "Embedder not configured on app.state."
        raise RuntimeError(msg)
    return embedder


ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
AuditStorageDep = Annotated[ObjectStorage, Depends(get_audit_storage)]
TemporalClientDep = Annotated[TemporalClient, Depends(get_temporal_client)]
RerankerDep = Annotated[Reranker, Depends(get_reranker)]
RedisDep = Annotated["Redis | None", Depends(get_redis)]
IdempotencyDep = Annotated[IdempotencyService, Depends(get_idempotency_service)]
BudgetReservationDep = Annotated[
    BudgetReservationService, Depends(get_budget_reservation_service)
]
RetrievalClientDep = Annotated[
    "RetrievalClient | None", Depends(get_retrieval_client)
]
EmbedderDep = Annotated[LiteLLMEmbedder, Depends(get_embedder)]
