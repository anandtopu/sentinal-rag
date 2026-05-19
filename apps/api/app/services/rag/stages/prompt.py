"""PromptStage — resolve the prompt version via PromptService."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_service import DEFAULT_RAG_PROMPT_NAME, PromptService
from app.services.rag.types import QueryContext


class PromptStage:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, ctx: QueryContext) -> None:
        prompt_service = PromptService(self._session)
        ctx.resolved_prompt = await prompt_service.resolve_for_task(
            tenant_id=ctx.auth.tenant_id,
            task_type=DEFAULT_RAG_PROMPT_NAME,
            explicit_version_id=ctx.options.prompt_version_id,
        )
