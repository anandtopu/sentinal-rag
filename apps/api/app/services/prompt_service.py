"""Prompt service.

Enforces the at-most-one-default-per-template rule via partial unique index
(see migration 0006). The service layer handles the version-number sequencing
and the "set as default" toggle atomically: when set_as_default=True is passed
on create, it clears the existing default first.
"""

from __future__ import annotations

from uuid import UUID

from sentinelrag_shared.errors.exceptions import (
    ConflictError,
    NotFoundError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptTemplate, PromptVersion
from app.db.repositories.prompts import (
    PromptTemplateRepository,
    PromptVersionRepository,
)
from app.schemas.prompts import PromptTemplateCreate, PromptVersionCreate

DEFAULT_RAG_PROMPT_NAME = "rag_answer_generation"
DEFAULT_RAG_SYSTEM_PROMPT = (
    "You are SentinelRAG, an enterprise assistant. Answer ONLY from the "
    "provided context. If the context does not contain enough information, "
    "say you do not have enough information rather than guessing. "
    "Cite supporting passages inline using [1], [2], etc. corresponding to "
    "the numbered Context entries."
)
DEFAULT_RAG_USER_PROMPT_TEMPLATE = """\
Question: {query}

Context:
{context}

Answer using the context above. Include citation markers like [1], [2] for \
each claim. If the context is insufficient, say so."""


class PromptService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.templates = PromptTemplateRepository(db)
        self.versions = PromptVersionRepository(db)

    async def create_template(
        self,
        *,
        tenant_id: UUID,
        created_by: UUID | None,
        payload: PromptTemplateCreate,
    ) -> PromptTemplate:
        existing = await self.templates.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError(f"Prompt template '{payload.name}' already exists.")
        tmpl = PromptTemplate(
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            task_type=payload.task_type,
            created_by=created_by,
        )
        self.db.add(tmpl)
        await self.db.flush()
        return tmpl

    async def get_template(self, template_id: UUID) -> PromptTemplate:
        tmpl = await self.templates.get(template_id)
        if tmpl is None:
            raise NotFoundError("Prompt template not found.")
        return tmpl

    async def list_templates(self) -> list[PromptTemplate]:
        return await self.templates.list(limit=200)

    async def create_version(
        self,
        *,
        tenant_id: UUID,
        template_id: UUID,
        created_by: UUID | None,
        payload: PromptVersionCreate,
    ) -> PromptVersion:
        await self.get_template(template_id)
        next_num = (await self.versions.latest_version_number(template_id)) + 1

        if payload.set_as_default:
            # Clear any existing default first to satisfy the partial unique
            # index in 0006_prompts.
            await self.db.execute(
                text(
                    "UPDATE prompt_versions SET is_default = false "
                    "WHERE prompt_template_id = :tid AND is_default = true"
                ),
                {"tid": str(template_id)},
            )

        version = PromptVersion(
            tenant_id=tenant_id,
            prompt_template_id=template_id,
            version_number=next_num,
            system_prompt=payload.system_prompt,
            user_prompt_template=payload.user_prompt_template,
            parameters=payload.parameters,
            model_config_=payload.model_config_,
            is_default=payload.set_as_default,
            created_by=created_by,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def list_versions(self, template_id: UUID) -> list[PromptVersion]:
        await self.get_template(template_id)
        return await self.versions.list_for_template(template_id)

    async def get_version(self, version_id: UUID) -> PromptVersion:
        v = await self.versions.get(version_id)
        if v is None:
            raise NotFoundError("Prompt version not found.")
        return v

    async def resolve_for_task(
        self,
        *,
        tenant_id: UUID,
        task_type: str,
        explicit_version_id: UUID | None = None,
    ) -> PromptVersion:
        """Resolve which prompt to use for a given task.

        Priority:
            1. Explicit ``prompt_version_id`` from the request (validated).
            2. Tenant's default version of the named ``task_type`` template.
            3. Seeded tenant default for built-in RAG answer generation.
        """
        if explicit_version_id is not None:
            return await self.get_version(explicit_version_id)

        # Look up the tenant's template by ``task_type`` name. If none exists
        # for the built-in RAG task, seed version 1 so generated answers always
        # reference a persisted prompt artifact.
        template = await self.templates.get_by_name(task_type)
        if template is None:
            if task_type != DEFAULT_RAG_PROMPT_NAME:
                raise NotFoundError(f"Prompt template for task '{task_type}' not found.")
            return await self._seed_default_rag_prompt(tenant_id=tenant_id)
        version = await self.versions.get_default(template.id)
        if version is None:
            raise NotFoundError(f"Default prompt version for task '{task_type}' not found.")
        return version

    async def _seed_default_rag_prompt(self, *, tenant_id: UUID) -> PromptVersion:
        template = PromptTemplate(
            tenant_id=tenant_id,
            name=DEFAULT_RAG_PROMPT_NAME,
            description="Seeded default prompt for grounded RAG answer generation.",
            task_type=DEFAULT_RAG_PROMPT_NAME,
            created_by=None,
        )
        self.db.add(template)
        await self.db.flush()

        version = PromptVersion(
            tenant_id=tenant_id,
            prompt_template_id=template.id,
            version_number=1,
            system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
            user_prompt_template=DEFAULT_RAG_USER_PROMPT_TEMPLATE,
            parameters={},
            model_config_={},
            is_default=True,
            created_by=None,
        )
        self.db.add(version)
        await self.db.flush()
        return version
