"""EvaluationRunWorkflow — drives per-case scoring sequentially.

For each case in the dataset:
    1. score_case (which runs the orchestrator + evaluators + persists)

Sequential by default — eval workloads aren't latency-sensitive and
sequential simplifies tenant-context binding. Phase 6 may parallelize via
fan-out activities + child workflows when datasets grow.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sentinelrag_shared.contracts import (
        EvaluationRunWorkflowInput,
        EvaluationRunWorkflowResult,
    )

    from sentinelrag_worker.activities import evaluation as activities


_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)


@workflow.defn(name="EvaluationRunWorkflow")
class EvaluationRunWorkflow:
    @workflow.run
    async def run(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        payload = EvaluationRunWorkflowInput.model_validate(raw_payload)

        await workflow.execute_activity(
            activities.mark_run_running,
            args=[str(payload.evaluation_run_id), str(payload.tenant_id)],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_RETRY,
        )

        case_ids: list[str] = await workflow.execute_activity(
            activities.list_case_ids,
            args=[str(payload.dataset_id), str(payload.tenant_id)],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_RETRY,
        )

        cases_completed = 0
        cases_failed = 0
        for case_id in case_ids:
            try:
                await workflow.execute_activity(
                    activities.score_case,
                    kwargs={
                        "run_id": str(payload.evaluation_run_id),
                        "case_id": case_id,
                        "tenant_id": str(payload.tenant_id),
                        "actor_user_id": str(payload.actor_user_id)
                        if payload.actor_user_id
                        else None,
                        "collection_ids": [str(c) for c in payload.collection_ids],
                        "prompt_version_id": str(payload.prompt_version_id)
                        if payload.prompt_version_id
                        else None,
                        "model_config": payload.model_config_,
                        "retrieval_config": payload.retrieval_config,
                    },
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                cases_completed += 1
            except Exception as exc:
                cases_failed += 1
                await workflow.execute_activity(
                    activities.record_case_failure,
                    args=[
                        str(payload.evaluation_run_id),
                        case_id,
                        str(payload.tenant_id),
                        str(exc),
                    ],
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=_RETRY,
                )

        final_status = "failed" if cases_failed else "completed"
        await workflow.execute_activity(
            activities.finalize_run,
            args=[str(payload.evaluation_run_id), str(payload.tenant_id), final_status],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_RETRY,
        )

        result = EvaluationRunWorkflowResult(
            evaluation_run_id=payload.evaluation_run_id,
            cases_completed=cases_completed,
            cases_failed=cases_failed,
        )
        return result.model_dump(mode="json")
