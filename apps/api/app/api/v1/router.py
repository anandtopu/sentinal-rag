"""v1 API router aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    collections,
    documents,
    evaluations,
    health,
    ingestion,
    prompts,
    query,
    roles,
    tenants,
    users,
)

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(tenants.router)
api_v1_router.include_router(users.router)
api_v1_router.include_router(roles.router)
api_v1_router.include_router(collections.router)
api_v1_router.include_router(documents.router)
api_v1_router.include_router(ingestion.router)
api_v1_router.include_router(query.router)
api_v1_router.include_router(prompts.router)
api_v1_router.include_router(evaluations.router)

# Phase 6+ will add: audit, usage.
