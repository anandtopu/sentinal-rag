"""Application lifespan: startup + shutdown hooks.

Bootstraps logging, telemetry, the JWT verifier, the ObjectStorage adapter,
the Temporal client, and disposes the DB engine on shutdown. The DB engine
is created lazily on first use (see ``app/db/session.py``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sentinelrag_shared.auth import JWTVerifier
from sentinelrag_shared.llm import BgeReranker, NoOpReranker
from sentinelrag_shared.logging import configure_logging, get_logger
from sentinelrag_shared.object_storage import build_object_storage
from sentinelrag_shared.telemetry import configure_telemetry
from temporalio.client import Client as TemporalClient

from app.core.config import get_settings
from app.db.session import dispose_engines


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    configure_logging(
        level=settings.log_level,
        json_output=settings.environment != "local",
        service_name=settings.service_name,
    )
    configure_telemetry(
        service_name=settings.service_name,
        service_version=settings.service_version,
        environment=settings.environment,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
    )

    log = get_logger(__name__)

    # Pre-warm the tiktoken encoding used by chunkers. The first call to
    # ``tiktoken.get_encoding`` downloads a ~2MB blob; doing it here keeps
    # the first real request fast.
    try:
        import tiktoken  # noqa: PLC0415

        tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        log.warning("tiktoken.prewarm_failed", error=str(exc))

    # JWT verifier — single instance per process, JWKS cached.
    app.state.jwt_verifier = JWTVerifier(
        issuer=settings.keycloak_issuer_url,
        audience=settings.keycloak_audience,
        jwks_url=settings.keycloak_jwks_url,
        algorithms=(settings.jwt_algorithm,),
    )

    # Object storage adapter (per-tenant operations open clients per call,
    # so there's no long-lived connection here — the adapter is just config).
    app.state.object_storage = build_object_storage(
        provider=settings.object_storage_provider,
        bucket=settings.object_storage_bucket_documents,
        region=settings.object_storage_region,
        endpoint=settings.object_storage_endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
        verify_ssl=settings.environment != "local",
    )
    app.state.audit_storage = build_object_storage(
        provider=settings.object_storage_provider,
        bucket=settings.object_storage_bucket_audit,
        region=settings.object_storage_region,
        endpoint=settings.object_storage_endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
        verify_ssl=settings.environment != "local",
    )

    # Reranker — load the heavy model only when explicitly enabled. Defaults
    # to NoOpReranker (preserves merged ordering) so tests + local smoke runs
    # don't pay the ~3-10s model-load cost.
    if settings.enable_reranker:
        try:
            app.state.reranker = BgeReranker(model_name=settings.default_reranker_model)
            # Trigger lazy load now so the first /query is fast.
            app.state.reranker._ensure_model()  # pyright: ignore[reportPrivateUsage]
            log.info("reranker.loaded", model=settings.default_reranker_model)
        except Exception as exc:
            log.warning("reranker.load_failed", error=str(exc))
            app.state.reranker = NoOpReranker()
    else:
        app.state.reranker = NoOpReranker()

    # Temporal client — connects on first use; ``Client.connect`` is async.
    try:
        app.state.temporal_client = await TemporalClient.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
        log.info(
            "service.startup",
            environment=settings.environment,
            version=settings.service_version,
            temporal_host=settings.temporal_host,
        )
    except Exception as exc:
        # In local dev the API may start before Temporal — log + continue.
        # Routes that need Temporal will fail with 500 until a reconnect.
        log.warning(
            "temporal.connect_failed",
            error=str(exc),
            host=settings.temporal_host,
        )
        app.state.temporal_client = None

    try:
        yield
    finally:
        log.info("service.shutdown")
        await app.state.jwt_verifier.close()
        if getattr(app.state, "object_storage", None) is not None:
            await app.state.object_storage.close()
        if getattr(app.state, "audit_storage", None) is not None:
            await app.state.audit_storage.close()
        await dispose_engines()
