"""Unit tests for Temporal worker runtime settings."""

from __future__ import annotations

import pytest
from sentinelrag_worker.settings import (
    DEFAULT_DATABASE_URL,
    env_bool,
    env_int,
    get_database_url,
    load_worker_settings,
)


@pytest.mark.unit
def test_database_url_default_matches_local_docker_port() -> None:
    assert get_database_url({}) == DEFAULT_DATABASE_URL
    assert "localhost:15432" in DEFAULT_DATABASE_URL


@pytest.mark.unit
def test_worker_settings_loads_queue_names_from_environment() -> None:
    settings = load_worker_settings(
        {
            "ENVIRONMENT": "prod",
            "TEMPORAL_HOST": "temporal:7233",
            "TEMPORAL_NAMESPACE": "sentinelrag",
            "TEMPORAL_TASK_QUEUE_INGESTION": "ingest-prod",
            "TEMPORAL_TASK_QUEUE_EVALUATION": "eval-prod",
            "TEMPORAL_TASK_QUEUE_AUDIT": "audit-prod",
        }
    )

    assert settings.environment == "prod"
    assert settings.temporal_host == "temporal:7233"
    assert settings.temporal_namespace == "sentinelrag"
    assert settings.ingestion_task_queue == "ingest-prod"
    assert settings.evaluation_task_queue == "eval-prod"
    assert settings.audit_task_queue == "audit-prod"


@pytest.mark.unit
def test_env_int_and_bool_validate_values() -> None:
    assert env_int("COUNT", default=1, minimum=1, environ={"COUNT": "3"}) == 3
    assert env_bool("FLAG", default=False, environ={"FLAG": "yes"}) is True

    with pytest.raises(ValueError, match="COUNT"):
        env_int("COUNT", default=1, minimum=1, environ={"COUNT": "0"})

    with pytest.raises(ValueError, match="FLAG"):
        env_bool("FLAG", default=False, environ={"FLAG": "sometimes"})
