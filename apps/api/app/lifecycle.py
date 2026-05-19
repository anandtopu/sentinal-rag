"""Application lifespan: startup + shutdown hooks.

Bootstraps logging, telemetry, the JWT verifier, the ObjectStorage adapter,
the Temporal client, and disposes the DB engine on shutdown. The DB engine
is created lazily on first use (see ``app/db/session.py``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sentinelrag_shared.auth import JWTVerifier
from sentinelrag_shared.llm import BgeReranker, LiteLLMEmbedder, NoOpReranker
from sentinelrag_shared.logging import configure_logging, get_logger
from sentinelrag_shared.object_storage import build_object_storage
from sentinelrag_shared.telemetry import configure_telemetry
from temporalio.client import Client as TemporalClient

from app.core.config import Settings, get_settings
from app.db.session import dispose_engines
from app.services.rag.client import HttpRetrievalClient, RetrievalClient
from app.services.redis_service import build_redis_client, ping_or_none


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

    # Redis client (R3.S2 + R3.S5). Both features degrade to no-op
    # when Redis is unreachable so the API stays up in partial outages.
    app.state.redis = await _connect_redis(redis_url=settings.redis_url, log=log)

    # Retrieval client selector (R4.S3). The orchestrator accepts a
    # ``RetrievalClient | None`` and falls back to per-request
    # ``InProcessRetrievalClient`` construction when None is passed,
    # which is exactly what we want for ``in-process`` mode (the
    # SQLAlchemy session needed for the in-process backend is
    # per-request, not process-wide). The HTTP client *is* a
    # process-wide singleton.
    app.state.retrieval_client = _build_retrieval_client(settings=settings, log=log)

    # R3.S6: process-singleton embedder. Per-request construction was
    # ~50µs but mostly garbage allocation; hoisting drops that from
    # every /query call. The Temporal worker keeps its per-request
    # path because it overrides the model alias per evaluation run.
    app.state.embedder = LiteLLMEmbedder(
        model_name=settings.default_embedding_model,
        api_base=settings.ollama_base_url
        if settings.default_embedding_model.startswith("ollama/")
        else None,
    )
    log.info("embedder.loaded", model=settings.default_embedding_model)

    # Temporal client — connects on first use; ``Client.connect`` is async.
    app.state.temporal_client = await _connect_temporal(settings=settings, log=log)

    try:
        yield
    finally:
        log.info("service.shutdown")
        await app.state.jwt_verifier.close()
        if getattr(app.state, "object_storage", None) is not None:
            await app.state.object_storage.close()
        if getattr(app.state, "audit_storage", None) is not None:
            await app.state.audit_storage.close()
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception as exc:
                log.warning("redis.close_failed", error=str(exc))
        retrieval_client = getattr(app.state, "retrieval_client", None)
        if isinstance(retrieval_client, HttpRetrievalClient):
            try:
                await retrieval_client.aclose()
            except Exception as exc:
                log.warning("retrieval_client.close_failed", error=str(exc))
        await dispose_engines()


def _build_retrieval_client(
    *, settings: Settings, log: Any
) -> RetrievalClient | None:
    """Materialize the right RetrievalClient for ``RETRIEVAL_TRANSPORT``.

    Returns ``None`` for in-process transport — the orchestrator's
    existing fallback constructs a per-request
    :class:`InProcessRetrievalClient` against the request-scoped
    SQLAlchemy session (the right lifetime).

    For ``http`` transport the client is a process-wide singleton — the
    underlying httpx connection pool is reused across requests, which
    is the whole point of the extraction.
    """
    transport = settings.retrieval_transport
    if transport == "in-process":
        log.info("retrieval.transport", transport=transport)
        return None
    if transport == "http":
        # R6.S3 follow-up from R4: fail loud at startup if the operator
        # set ``RETRIEVAL_TRANSPORT=http`` but forgot to seed the token.
        # The retrieval-service would 503 the first call anyway, but
        # surfacing it here means the API pod never accepts traffic in
        # a broken config rather than 503'ing every /query for hours.
        if not settings.retrieval_service_token:
            msg = (
                "RETRIEVAL_TRANSPORT=http but RETRIEVAL_SERVICE_TOKEN is empty. "
                "Set the shared bearer secret (per ADR-0031) before starting "
                "the API, or set RETRIEVAL_TRANSPORT=in-process for local dev."
            )
            raise RuntimeError(msg)
        log.info(
            "retrieval.transport",
            transport=transport,
            base_url=settings.retrieval_service_url,
        )
        return HttpRetrievalClient(
            base_url=settings.retrieval_service_url,
            service_token=settings.retrieval_service_token,
            timeout_seconds=settings.retrieval_service_timeout_seconds,
        )
    # Pydantic Literal narrows this to one of the two strings, but be
    # defensive against a typed-config mismatch.
    msg = (
        f"Unknown RETRIEVAL_TRANSPORT {transport!r}; "
        "expected 'in-process' or 'http'."
    )
    raise RuntimeError(msg)


async def _connect_temporal(
    *, settings: Settings, log: Any
) -> TemporalClient | None:
    """Best-effort Temporal connect on startup; None on failure."""
    try:
        client = await TemporalClient.connect(
            settings.temporal_host, namespace=settings.temporal_namespace
        )
    except Exception as exc:
        log.warning(
            "temporal.connect_failed",
            error=str(exc),
            host=settings.temporal_host,
        )
        return None
    log.info(
        "service.startup",
        environment=settings.environment,
        version=settings.service_version,
        temporal_host=settings.temporal_host,
    )
    return client


async def _connect_redis(*, redis_url: str, log: Any) -> Any | None:
    """Build the async Redis client and probe it. Returns None on failure."""
    try:
        client = build_redis_client(redis_url=redis_url)
    except Exception as exc:
        log.warning("redis.connect_failed", error=str(exc), url=redis_url)
        return None
    if await ping_or_none(client):
        log.info("redis.connected", url=redis_url)
    else:
        log.warning("redis.ping_failed_features_degraded", url=redis_url)
    return client
