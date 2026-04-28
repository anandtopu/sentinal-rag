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
import os

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
from sentinelrag_worker.workflows.audit_reconciliation import (
    AuditReconciliationWorkflow,
)
from sentinelrag_worker.workflows.evaluation import EvaluationRunWorkflow
from sentinelrag_worker.workflows.ingestion import IngestionWorkflow


async def main() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    environment = os.environ.get("ENVIRONMENT", "local")
    configure_logging(
        level=log_level,
        json_output=environment != "local",
        service_name="sentinelrag-temporal-worker",
    )
    configure_telemetry(
        service_name="sentinelrag-temporal-worker",
        service_version="0.1.0",
        environment=environment,
        otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )

    log = get_logger(__name__)

    # Pre-warm tiktoken before activities run.
    try:
        import tiktoken  # noqa: PLC0415

        tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        log.warning("tiktoken.prewarm_failed", error=str(exc))

    host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    ingestion_queue = os.environ.get("TEMPORAL_TASK_QUEUE_INGESTION", "ingestion")
    evaluation_queue = os.environ.get("TEMPORAL_TASK_QUEUE_EVALUATION", "evaluation")
    audit_queue = os.environ.get("TEMPORAL_TASK_QUEUE_AUDIT", "audit")

    log.info(
        "temporal_worker.starting",
        host=host,
        namespace=namespace,
        ingestion_queue=ingestion_queue,
        evaluation_queue=evaluation_queue,
        audit_queue=audit_queue,
    )

    client = await Client.connect(host, namespace=namespace)

    ingestion_worker = Worker(
        client,
        task_queue=ingestion_queue,
        workflows=[IngestionWorkflow],
        activities=INGESTION_ACTIVITIES,
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=20,
    )

    evaluation_worker = Worker(
        client,
        task_queue=evaluation_queue,
        workflows=[EvaluationRunWorkflow],
        activities=EVALUATION_ACTIVITIES,
        max_concurrent_activities=4,  # eval activities are heavier (LLM calls)
        max_concurrent_workflow_tasks=10,
    )

    audit_worker = Worker(
        client,
        task_queue=audit_queue,
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
