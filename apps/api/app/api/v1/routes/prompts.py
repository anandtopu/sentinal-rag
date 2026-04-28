"""Prompt registry routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.session import get_db
from app.schemas.prompts import (
    PromptTemplateCreate,
    PromptTemplateRead,
    PromptVersionCreate,
    PromptVersionRead,
)
from app.services.prompt_service import PromptService

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post(
    "",
    response_model=PromptTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_template(
    payload: PromptTemplateCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("prompts:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PromptTemplateRead:
    service = PromptService(db)
    tmpl = await service.create_template(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payload=payload
    )
    return PromptTemplateRead.model_validate(tmpl)


@router.get("", response_model=list[PromptTemplateRead])
async def list_prompt_templates(
    _ctx: Annotated[AuthContext, Depends(require_permission("prompts:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PromptTemplateRead]:
    service = PromptService(db)
    items = await service.list_templates()
    return [PromptTemplateRead.model_validate(t) for t in items]


@router.get("/{template_id}", response_model=PromptTemplateRead)
async def read_prompt_template(
    template_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("prompts:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PromptTemplateRead:
    service = PromptService(db)
    tmpl = await service.get_template(template_id)
    return PromptTemplateRead.model_validate(tmpl)


@router.post(
    "/{template_id}/versions",
    response_model=PromptVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_version(
    template_id: UUID,
    payload: PromptVersionCreate,
    ctx: Annotated[AuthContext, Depends(require_permission("prompts:admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PromptVersionRead:
    service = PromptService(db)
    version = await service.create_version(
        tenant_id=ctx.tenant_id,
        template_id=template_id,
        created_by=ctx.user_id,
        payload=payload,
    )
    return PromptVersionRead.model_validate(version)


@router.get("/{template_id}/versions", response_model=list[PromptVersionRead])
async def list_prompt_versions(
    template_id: UUID,
    _ctx: Annotated[AuthContext, Depends(require_permission("prompts:read"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PromptVersionRead]:
    service = PromptService(db)
    versions = await service.list_versions(template_id)
    return [PromptVersionRead.model_validate(v) for v in versions]
