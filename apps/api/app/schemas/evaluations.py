"""Pydantic schemas for evaluation API I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class EvaluationDatasetCreate(APIModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    dataset_type: str = Field(default="golden")


class EvaluationDatasetRead(APIModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    dataset_type: str
    created_at: datetime


class EvaluationCaseCreate(APIModel):
    input_query: str = Field(..., min_length=1)
    expected_answer: str | None = None
    expected_citation_chunk_ids: list[UUID] = Field(default_factory=list)
    grading_rubric: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseRead(APIModel):
    id: UUID
    dataset_id: UUID
    input_query: str
    expected_answer: str | None
    expected_citation_chunk_ids: list[UUID]
    grading_rubric: dict[str, Any]
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime


class EvaluationRunCreate(APIModel):
    dataset_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    prompt_version_id: UUID | None = None
    collection_ids: list[UUID] = Field(..., min_length=1)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    model_config_: dict[str, Any] = Field(default_factory=dict, alias="model_config")


class EvaluationRunRead(APIModel):
    id: UUID
    dataset_id: UUID
    name: str
    status: str
    workflow_id: str | None
    prompt_version_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class EvaluationScoreSummary(APIModel):
    context_relevance_avg: float | None
    faithfulness_avg: float | None
    answer_correctness_avg: float | None
    citation_accuracy_avg: float | None
    average_latency_ms: int | None
    total_cost_usd: float | None
    cases_total: int
    cases_completed: int


class EvaluationRunResults(APIModel):
    evaluation_run_id: UUID
    status: str
    summary: EvaluationScoreSummary
