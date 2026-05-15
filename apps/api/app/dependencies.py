"""Shared FastAPI dependencies that build singleton-style resources from app state.

The Temporal client, ObjectStorage adapter, and Reranker are constructed once
at startup (see ``app/lifecycle.py``) and stored on ``request.app.state``.
These dependency factories pull them out for routes that need them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sentinelrag_shared.errors import TemporalUnavailableError
from sentinelrag_shared.llm import Reranker
from sentinelrag_shared.object_storage import ObjectStorage
from temporalio.client import Client as TemporalClient


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


ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
AuditStorageDep = Annotated[ObjectStorage, Depends(get_audit_storage)]
TemporalClientDep = Annotated[TemporalClient, Depends(get_temporal_client)]
RerankerDep = Annotated[Reranker, Depends(get_reranker)]
