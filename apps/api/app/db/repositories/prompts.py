"""Prompt template + version repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.db.models import PromptTemplate, PromptVersion
from app.db.repositories.base import BaseRepository


class PromptTemplateRepository(BaseRepository[PromptTemplate]):
    model = PromptTemplate

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        stmt = select(PromptTemplate).where(PromptTemplate.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class PromptVersionRepository(BaseRepository[PromptVersion]):
    model = PromptVersion

    async def latest_version_number(self, template_id: UUID) -> int:
        stmt = select(func.max(PromptVersion.version_number)).where(
            PromptVersion.prompt_template_id == template_id
        )
        result = await self.session.execute(stmt)
        n = result.scalar_one()
        return int(n) if n else 0

    async def get_default(self, template_id: UUID) -> PromptVersion | None:
        stmt = (
            select(PromptVersion)
            .where(
                PromptVersion.prompt_template_id == template_id,
                PromptVersion.is_default.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get(self, version_id: UUID) -> PromptVersion | None:
        return await super().get(version_id)

    async def list_for_template(self, template_id: UUID) -> list[PromptVersion]:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_template_id == template_id)
            .order_by(PromptVersion.version_number.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
