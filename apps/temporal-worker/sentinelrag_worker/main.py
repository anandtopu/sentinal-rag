"""Temporal worker entry point.

Connects to the Temporal cluster, registers workflows + activities, and runs
forever. Two task queues:

    - ``ingestion``  — IngestionWorkflow + ingestion activities.
    - ``evaluation`` — EvaluationRunWorkflow + evaluation activities.

Each queue gets its own Worker; both run inside this single process.
Production may split into separate pods if eval load justifies it.

Run locally with:
    uv run --package sentinelrag-temporal-worker python -m sentinelrag_worker.main
"""

from __future__ import annotations

import asyncio

from sentinelrag_shared.logging import configure_logging, get_logger
from sentinelrag_shared.telemetry import configure_telemetry
from temporalio.client import Client
from temporalio.worker import Worker

from sentinelrag_worker.activities.audit_reconciliation import (
    ALL_ACTIVITIES as AUDIT_ACTIVITIES,
)
from sentinelrag_worker.activities.evaluation import (
    ALL_ACTIVITIES as EVALUATION_ACTIVITIES,
)
from sentinelrag_worker.activities.ingestion import (
    ALL_ACTIVITIES as INGESTION_ACTIVITIES,
)
from sentinelrag_worker.settings import load_worker_settings
from sentinelrag_worker.workflows.audit_reconciliation import (
    AuditReconciliationWorkflow,
)
from sentinelrag_worker.workflows.evaluation import EvaluationRunWorkflow
from sentinelrag_worker.workflows.ingestion import IngestionWorkflow


async def main() -> None:
    settings = load_worker_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.environment != "local",
        service_name="sentinelrag-temporal-worker",
    )
    configure_telemetry(
        service_name="sentinelrag-temporal-worker",
        service_version="0.1.0",
        environment=settings.environment,
        otlp_endpoint=settings.otlp_endpoint,
    )

    log = get_logger(__name__)

    # Pre-warm tiktoken before activities run.
    try:
        import tiktoken  # noqa: PLC0415

        tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        log.warning("tiktoken.prewarm_failed", error=str(exc))

    log.info(
        "temporal_worker.starting",
        host=settings.temporal_host,
        namespace=settings.temporal_namespace,
        ingestion_queue=settings.ingestion_task_queue,
        evaluation_queue=settings.evaluation_task_queue,
        audit_queue=settings.audit_task_queue,
    )

    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)

    ingestion_worker = Worker(
        client,
        task_queue=settings.ingestion_task_queue,
        workflows=[IngestionWorkflow],
        activities=INGESTION_ACTIVITIES,
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=20,
    )

    evaluation_worker = Worker(
        client,
        task_queue=settings.evaluation_task_queue,
        workflows=[EvaluationRunWorkflow],
        activities=EVALUATION_ACTIVITIES,
        max_concurrent_activities=4,  # eval activities are heavier (LLM calls)
        max_concurrent_workflow_tasks=10,
    )

    audit_worker = Worker(
        client,
        task_queue=settings.audit_task_queue,
        workflows=[AuditReconciliationWorkflow],
        activities=AUDIT_ACTIVITIES,
        max_concurrent_activities=4,
        max_concurrent_workflow_tasks=2,  # one daily run; near-zero throughput
    )

    log.info("temporal_worker.ready")
    # Run all workers concurrently. ``Worker.run()`` blocks until cancelled.
    await asyncio.gather(
        ingestion_worker.run(),
        evaluation_worker.run(),
        audit_worker.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
