"""Runtime settings for the Temporal worker process."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    log_level: str
    environment: str
    temporal_host: str
    temporal_namespace: str
    ingestion_task_queue: str
    evaluation_task_queue: str
    audit_task_queue: str
    otlp_endpoint: str | None


def get_database_url(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    return env.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def env_bool(
    name: str,
    *,
    default: bool,
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = environ or os.environ
    raw = env.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    msg = f"{name} must be a boolean value."
    raise ValueError(msg)


def env_int(
    name: str,
    *,
    default: int,
    minimum: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = environ or os.environ
    raw = env.get(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        msg = f"{name} must be an integer."
        raise ValueError(msg) from exc
    if minimum is not None and value < minimum:
        msg = f"{name} must be >= {minimum}."
        raise ValueError(msg)
    return value


def load_worker_settings(environ: Mapping[str, str] | None = None) -> WorkerSettings:
    env = environ or os.environ
    return WorkerSettings(
        log_level=env.get("LOG_LEVEL", "INFO"),
        environment=env.get("ENVIRONMENT", "local"),
        temporal_host=env.get("TEMPORAL_HOST", "localhost:7233"),
        temporal_namespace=env.get("TEMPORAL_NAMESPACE", "default"),
        ingestion_task_queue=env.get("TEMPORAL_TASK_QUEUE_INGESTION", "ingestion"),
        evaluation_task_queue=env.get("TEMPORAL_TASK_QUEUE_EVALUATION", "evaluation"),
        audit_task_queue=env.get("TEMPORAL_TASK_QUEUE_AUDIT", "audit"),
        otlp_endpoint=env.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
