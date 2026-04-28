"""Pydantic schemas for prompt registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class PromptTemplateCreate(APIModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    task_type: str = Field(..., min_length=1, max_length=64)


class PromptTemplateRead(APIModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    task_type: str
    status: str
    created_at: datetime


class PromptVersionCreate(APIModel):
    system_prompt: str = Field(..., min_length=1)
    user_prompt_template: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    model_config_: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    set_as_default: bool = False


class PromptVersionRead(APIModel):
    id: UUID
    prompt_template_id: UUID
    version_number: int
    system_prompt: str
    user_prompt_template: str
    parameters: dict[str, Any]
    model_config_: dict[str, Any] = Field(alias="model_config")
    is_default: bool
    created_at: datetime
