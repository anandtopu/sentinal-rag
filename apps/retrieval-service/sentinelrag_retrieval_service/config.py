"""Settings for apps/retrieval-service.

Mirrors a small slice of the API service settings — only the values the
retrieval service actually needs at request time. Loaded from env via
``pydantic-settings``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "sentinelrag-retrieval-service"
    service_version: str = "0.1.0"
    log_level: str = "INFO"

    # --- DB ---
    database_url: str = (
        "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag"
    )

    # --- Embedding (must match the API's default so the chunk_embeddings
    # rows are usable). ADR-0020 supports 768/1024/1536 in v1. ---
    default_embedding_model: str = "ollama/nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"

    # --- Service-to-service auth ---
    # Shared bearer secret with the API service. Empty default → the
    # ``/v1/retrieve`` route returns 503 (not configured) rather than
    # silently letting unauthenticated traffic in.
    service_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
