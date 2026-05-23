"""FastAPI application entry point.

Run locally with:
    uv run --package sentinelrag-api uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.lifecycle import lifespan
from app.middleware.error_handler import register_error_handlers
from app.middleware.request_context import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SentinelRAG API",
        version=settings.service_version,
        description=(
            "Multi-tenant, RBAC-aware, evaluation-driven enterprise RAG platform. "
            "See Enterprise_RAG_Database_Design.md for the full API contract."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_base_path}/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_v1_router, prefix=settings.api_base_path)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
