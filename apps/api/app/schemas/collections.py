"""Pydantic schemas for collections API I/O."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import APIModel, FullTimestampedRead

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}$")


class CollectionCreate(APIModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    visibility: str = Field(default="private")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            msg = "name must start with alphanumeric and contain only [A-Za-z0-9 _.-]"
            raise ValueError(msg)
        return v

    @field_validator("visibility")
    @classmethod
    def _validate_visibility(cls, v: str) -> str:
        if v not in {"private", "tenant", "public"}:
            msg = "visibility must be one of: private, tenant, public"
            raise ValueError(msg)
        return v


class CollectionUpdate(APIModel):
    description: str | None = Field(default=None, max_length=1000)
    visibility: str | None = None
    metadata: dict[str, Any] | None = None


class CollectionRead(FullTimestampedRead):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    visibility: str
    metadata: dict[str, Any] = Field(alias="metadata_")
