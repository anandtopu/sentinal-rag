"""IngestionWorkflow — durable parse → chunk → embed → index pipeline.

Per ADR-0007, this is a Temporal workflow (not Celery) so a worker crash
mid-job resumes from the last completed activity rather than restarting.

Each activity is idempotent on ``(tenant_id, document_id, version_id)`` so
retries don't duplicate chunks or embeddings.

Input/output: typed Pydantic contracts in
``sentinelrag_shared.contracts.ingestion``. The Temporal client on the API
side serializes the model to JSON; we receive a dict here and reconstruct.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

# Activity references + contract reconstruction live behind the unsafe
# context manager because they import heavy non-deterministic modules
# (sqlalchemy, etc.).
with workflow.unsafe.imports_passed_through():
    from sentinelrag_shared.contracts import (
        IngestionWorkflowInput,
        IngestionWorkflowResult,
    )

    from sentinelrag_worker.activities import ingestion as activities


# Backward-compat alias for any older imports.
IngestionWorkflowInput = IngestionWorkflowInput  # noqa: PLW0127


_STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)


@workflow.defn(name="IngestionWorkflow")
class IngestionWorkflow:
    """Single-document ingestion. Multi-doc jobs fan out N of these."""

    @workflow.run
    async def run(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        # Validate the incoming payload through the typed contract. If the
        # API and worker drift on field names, this is where we catch it.
        payload = IngestionWorkflowInput.model_validate(raw_payload)

        await workflow.execute_activity(
            activities.mark_job_running,
            args=[str(payload.job_id), str(payload.tenant_id), str(payload.document_id)],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_STANDARD_RETRY,
        )

        try:
            download = await workflow.execute_activity(
                activities.download_and_hash,
                args=[str(payload.tenant_id), payload.storage_uri],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_STANDARD_RETRY,
            )

            version_id: str = await workflow.execute_activity(
                activities.upsert_document_version,
                args=[
                    str(payload.tenant_id),
                    str(payload.document_id),
                    download["content_hash"],
                    payload.storage_uri,
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_STANDARD_RETRY,
            )

            parse_result = await workflow.execute_activity(
                activities.parse_document,
                args=[
                    payload.storage_uri,
                    payload.mime_type,
                    str(payload.tenant_id),
                    payload.parsing_strategy,
                ],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            await workflow.execute_activity(
                activities.update_document_version_storage_uri,
                args=[
                    str(payload.tenant_id),
                    version_id,
                    parse_result["raw_text_uri"],
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_STANDARD_RETRY,
            )

            chunk_count: int = await workflow.execute_activity(
                activities.chunk_and_persist,
                args=[
                    str(payload.tenant_id),
                    str(payload.document_id),
                    version_id,
                    parse_result["elements_uri"],
                    payload.chunking_strategy,
                ],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_STANDARD_RETRY,
            )

            await workflow.execute_activity(
                activities.embed_chunks,
                args=[
                    str(payload.tenant_id),
                    version_id,
                    payload.embedding_model,
                ],
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=_STANDARD_RETRY,
            )

            await workflow.execute_activity(
                activities.finalize_document,
                args=[
                    str(payload.job_id),
                    str(payload.tenant_id),
                    str(payload.document_id),
                    chunk_count,
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_STANDARD_RETRY,
            )

            result = IngestionWorkflowResult(
                job_id=payload.job_id,
                document_version_id=version_id,
                chunks_created=chunk_count,
            )
            return result.model_dump(mode="json")

        except Exception as exc:
            await workflow.execute_activity(
                activities.mark_job_failed,
                args=[
                    str(payload.job_id),
                    str(payload.tenant_id),
                    str(payload.document_id),
                    str(exc)[:1000],
                ],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
