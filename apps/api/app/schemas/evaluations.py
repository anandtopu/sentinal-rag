"""Pydantic schemas for evaluation API I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import APIModel


class EvaluationDatasetCreate(APIModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    dataset_type: Literal["golden", "regression", "production_sample"] = "golden"


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

    @field_validator("grading_rubric")
    @classmethod
    def validate_rubric(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in ("must_include", "must_not_include"):
            if key in value and (
                not isinstance(value[key], list)
                or not all(isinstance(item, str) for item in value[key])
            ):
                msg = f"grading_rubric.{key} must be a list of strings."
                raise ValueError(msg)
        return value


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

    @field_validator("retrieval_config")
    @classmethod
    def validate_retrieval_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "mode",
            "top_k_bm25",
            "top_k_vector",
            "top_k_hybrid",
            "top_k_rerank",
            "ef_search",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            msg = f"Unknown retrieval_config keys: {', '.join(unknown)}."
            raise ValueError(msg)
        mode = value.get("mode")
        if mode is not None and mode not in {"hybrid", "bm25", "vector"}:
            raise ValueError("retrieval_config.mode must be hybrid, bm25, or vector.")
        for key in allowed - {"mode"}:
            if key in value and (not isinstance(value[key], int) or value[key] < 0):
                msg = f"retrieval_config.{key} must be a non-negative integer."
                raise ValueError(msg)
        return value

    @field_validator("model_config_")
    @classmethod
    def validate_model_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "model" in value and not isinstance(value["model"], str):
            raise ValueError("model_config.model must be a string.")
        if "embedding_model" in value and not isinstance(value["embedding_model"], str):
            raise ValueError("model_config.embedding_model must be a string.")
        if "temperature" in value and not isinstance(value["temperature"], int | float):
            raise ValueError("model_config.temperature must be numeric.")
        if "max_tokens" in value and (
            not isinstance(value["max_tokens"], int) or value["max_tokens"] <= 0
        ):
            raise ValueError("model_config.max_tokens must be a positive integer.")
        return value


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
    cases_failed: int = 0


class EvaluationRunResults(APIModel):
    evaluation_run_id: UUID
    status: str
    summary: EvaluationScoreSummary
