"""Evaluation workflow contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from sentinelrag_shared.contracts.base import Contract


class EvaluationRunWorkflowInput(Contract):
    evaluation_run_id: UUID
    tenant_id: UUID
    dataset_id: UUID
    collection_ids: list[UUID]
    prompt_version_id: UUID | None = None
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    model_config_: dict[str, Any] = Field(default_factory=dict, alias="model_config")


class EvaluationRunWorkflowResult(Contract):
    evaluation_run_id: UUID
    cases_completed: int = Field(..., ge=0)
