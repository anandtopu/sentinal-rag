"""Evaluation service.

Coordinates dataset CRUD, case management, and starting eval runs as Temporal
workflows. Results aggregation happens in the repository layer; the service
exposes a higher-level summary suitable for the UI.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sentinelrag_shared.errors.exceptions import (
    ConflictError,
    NotFoundError,
    TemporalUnavailableError,
)
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client as TemporalClient

from app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
)
from app.db.repositories.evaluations import (
    EvaluationCaseRepository,
    EvaluationDatasetRepository,
    EvaluationRunRepository,
    EvaluationScoreRepository,
)
from app.schemas.evaluations import (
    EvaluationCaseCreate,
    EvaluationDatasetCreate,
    EvaluationRunCreate,
)


class EvaluationService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        temporal_client: TemporalClient | None = None,
        evaluation_task_queue: str = "evaluation",
    ) -> None:
        self.db = db
        self.temporal = temporal_client
        self.evaluation_task_queue = evaluation_task_queue

        self.datasets = EvaluationDatasetRepository(db)
        self.cases = EvaluationCaseRepository(db)
        self.runs = EvaluationRunRepository(db)
        self.scores = EvaluationScoreRepository(db)

    async def create_dataset(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID | None,
        payload: EvaluationDatasetCreate,
    ) -> EvaluationDataset:
        existing = await self.datasets.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError(f"Dataset '{payload.name}' already exists.")
        ds = EvaluationDataset(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            dataset_type=payload.dataset_type,
            created_by=created_by,
        )
        self.db.add(ds)
        await self.db.flush()
        return ds

    async def list_datasets(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[EvaluationDataset]:
        return await self.datasets.list_recent(limit=limit, offset=offset)

    async def add_case(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        payload: EvaluationCaseCreate,
    ) -> EvaluationCase:
        ds = await self.datasets.get(dataset_id)
        if ds is None:
            raise NotFoundError("Dataset not found.")
        case = EvaluationCase(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            input_query=payload.input_query,
            expected_answer=payload.expected_answer,
            expected_citation_chunk_ids=payload.expected_citation_chunk_ids,
            grading_rubric=payload.grading_rubric,
            metadata_=payload.metadata,
        )
        self.db.add(case)
        await self.db.flush()
        return case

    async def list_cases(self, dataset_id: UUID) -> list[EvaluationCase]:
        return await self.cases.list_for_dataset(dataset_id)

    async def start_run(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID | None,
        payload: EvaluationRunCreate,
    ) -> EvaluationRun:
        ds = await self.datasets.get(payload.dataset_id)
        if ds is None:
            raise NotFoundError("Dataset not found.")

        run = EvaluationRun(
            tenant_id=tenant_id,
            dataset_id=payload.dataset_id,
            name=payload.name,
            model_config_=payload.model_config_,
            retrieval_config={
                **payload.retrieval_config,
                "collection_ids": [str(c) for c in payload.collection_ids],
            },
            prompt_version_id=payload.prompt_version_id,
            status="queued",
            created_by=created_by,
        )
        self.db.add(run)
        await self.db.flush()

        if self.temporal is not None:
            workflow_id = f"eval-{run.id}"
            try:
                await self.temporal.start_workflow(
                    "EvaluationRunWorkflow",
                    {
                        "evaluation_run_id": str(run.id),
                        "tenant_id": str(tenant_id),
                        "dataset_id": str(payload.dataset_id),
                        "actor_user_id": str(created_by) if created_by else None,
                        "collection_ids": [str(c) for c in payload.collection_ids],
                        "prompt_version_id": str(payload.prompt_version_id)
                        if payload.prompt_version_id
                        else None,
                        "retrieval_config": payload.retrieval_config,
                        "model_config": payload.model_config_,
                    },
                    id=workflow_id,
                    task_queue=self.evaluation_task_queue,
                )
            except Exception as exc:
                raise TemporalUnavailableError(
                    "Temporal is unavailable; evaluation run was not started."
                ) from exc
            run.workflow_id = workflow_id
            await self.db.flush()

        return run

    async def list_runs(self, *, limit: int = 50, offset: int = 0) -> list[EvaluationRun]:
        return await self.runs.list_recent(limit=limit, offset=offset)

    async def get_run(self, run_id: UUID) -> EvaluationRun:
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Evaluation run not found.")
        return run

    async def aggregate_run(
        self, run_id: UUID
    ) -> tuple[EvaluationRun, dict[str, Any]]:
        run = await self.get_run(run_id)
        agg = await self.scores.aggregate_for_run(run_id)
        cases_total = await self.cases.count_for_dataset(run.dataset_id)
        agg["cases_total"] = cases_total
        return run, agg
