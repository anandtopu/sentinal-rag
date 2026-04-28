"""Application settings.

Settings are loaded from environment variables (see ``.env.example``) via
pydantic-settings. The Settings instance is a process-wide singleton accessed
through :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    """API service runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service identity ---
    service_name: str = "sentinelrag-api"
    service_version: str = "0.1.0"
    environment: Environment = "local"
    log_level: str = "INFO"
    api_base_path: str = "/api/v1"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag",
        description="Async DSN; must use asyncpg driver.",
    )

    # --- Cache ---
    redis_url: str = "redis://localhost:6380/0"

    # --- Auth (Keycloak) ---
    keycloak_issuer_url: str = "http://localhost:8080/realms/sentinelrag"
    keycloak_audience: str = "sentinelrag-api"
    keycloak_jwks_url: str = (
        "http://localhost:8080/realms/sentinelrag/protocol/openid-connect/certs"
    )
    jwt_algorithm: str = "RS256"

    # --- Dev-only auth bypass (NEVER set true outside `local`) ---
    # When this is true AND environment == 'local', a request with header
    # ``Authorization: Bearer <dev_token_value>`` short-circuits Keycloak and
    # returns a synthesized AuthContext for the seeded demo tenant. Used by
    # local smoke tests and the ingestion integration tests.
    auth_allow_dev_token: bool = False
    dev_token_value: str = "dev"  # noqa: S105 — local-only sentinel, gated by environment check
    dev_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    dev_user_id: str = "00000000-0000-0000-0000-000000000010"
    dev_user_email: str = "demo-admin@sentinelrag.example.com"

    # --- Observability ---
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    # --- Temporal ---
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue_ingestion: str = "ingestion"
    temporal_task_queue_evaluation: str = "evaluation"

    # --- Object storage ---
    object_storage_provider: str = "minio"
    object_storage_endpoint: str = "http://localhost:9100"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"  # noqa: S105 — MinIO local-dev default
    object_storage_bucket_documents: str = "sentinelrag-documents"
    object_storage_bucket_audit: str = "sentinelrag-audit"
    object_storage_region: str = "us-east-1"

    # --- LLM defaults ---
    default_embedding_model: str = "ollama/nomic-embed-text"
    default_generation_model: str = "ollama/llama3.1:8b"
    default_reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # When True, the API process loads the bge-reranker model at startup.
    # Loading takes ~3-10s; for local smoke tests + CI we keep it OFF and the
    # orchestrator falls back to NoOpReranker. Set true for end-to-end demos.
    enable_reranker: bool = False
    ollama_base_url: str = "http://localhost:11434"

    # --- Feature flags ---
    unleash_url: str = "http://localhost:4242/api/"
    unleash_api_token: str = ""
    unleash_app_name: str = "sentinelrag-api"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
