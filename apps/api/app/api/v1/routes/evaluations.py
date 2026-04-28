"""Evaluation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies import TemporalClientDep
from app.schemas.evaluations import (
    EvaluationCaseCreate,
    EvaluationCaseRead,
    EvaluationDatasetCreate,
    EvaluationDatasetRead,
    EvaluationRunCreate,
    EvaluationRunRead,
    EvaluationRunResults,
    EvaluationScoreSummary,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.post(
    "/datasets",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("evals:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationDatasetRead:
    service = EvaluationService(db)
    ds = await service.create_dataset(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payload=payload
    )
    return EvaluationDatasetRead.model_validate(ds)


@router.post(
    "/datasets/{dataset_id}/cases",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_case(
    dataset_id: UUID,
    payload: EvaluationCaseCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("evals:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationCaseRead:
    service = EvaluationService(db)
    case = await service.add_case(
        tenant_id=ctx.tenant_id, dataset_id=dataset_id, payload=payload
    )
    return EvaluationCaseRead.model_validate(case)


@router.get(
    "/datasets/{dataset_id}/cases",
    response_model=list[EvaluationCaseRead],
)
async def list_cases(
    dataset_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("evals:run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EvaluationCaseRead]:
    service = EvaluationService(db)
    items = await service.list_cases(dataset_id)
    return [EvaluationCaseRead.model_validate(c) for c in items]


@router.post(
    "/runs",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    payload: EvaluationRunCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("evals:run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    temporal: TemporalClientDep,
) -> EvaluationRunRead:
    settings = get_settings()
    service = EvaluationService(
        db,
        temporal_client=temporal,
        evaluation_task_queue=settings.temporal_task_queue_evaluation,
    )
    run = await service.start_run(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payload=payload
    )
    return EvaluationRunRead.model_validate(run)


@router.get("/runs/{run_id}", response_model=EvaluationRunResults)
async def read_run(
    run_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("evals:run"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationRunResults:
    service = EvaluationService(db)
    run, agg = await service.aggregate_run(run_id)
    return EvaluationRunResults(
        evaluation_run_id=run.id,
        status=run.status,
        summary=EvaluationScoreSummary(**agg),
    )
