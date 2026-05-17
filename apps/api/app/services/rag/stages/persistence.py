"""PersistenceStage — write generated_answer + citations + usage_records.

All writes route through the repositories under ``app.db.repositories``;
no raw SQL lives in this module.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import (
    AnswerCitationRepository,
    GeneratedAnswerRepository,
    UsageRecordRepository,
)
from app.services.rag._helpers import referenced_indices
from app.services.rag.types import CitationOut, QueryContext


class PersistenceStage:
    def __init__(self, session: AsyncSession) -> None:
        self._answers = GeneratedAnswerRepository(session)
        self._citations = AnswerCitationRepository(session)
        self._usage = UsageRecordRepository(session)

    async def run(self, ctx: QueryContext) -> None:
        if ctx.query_session_id is None:
            msg = "PersistenceStage requires SessionStage.open to have run first."
            raise RuntimeError(msg)

        ctx.generated_answer_id = await self._persist_generated_answer(ctx)
        ctx.cited_out = await self._persist_citations(ctx)

        # Embedding row — tokens not surfaced in v1 (R3.S1 fixes this).
        await self._usage.create(
            tenant_id=ctx.auth.tenant_id,
            user_id=ctx.auth.user_id,
            query_session_id=ctx.query_session_id,
            usage_type="embedding",
            provider=ctx.embedder.model_name.split("/", 1)[0],
            model_name=ctx.embedder.model_name,
            input_tokens=0,
            output_tokens=0,
            total_cost_usd=Decimal("0"),
        )
        if ctx.gen_usage is not None:
            await self._usage.create(
                tenant_id=ctx.auth.tenant_id,
                user_id=ctx.auth.user_id,
                query_session_id=ctx.query_session_id,
                usage_type="completion",
                provider=ctx.gen_usage.provider,
                model_name=ctx.gen_usage.model_name,
                input_tokens=ctx.input_tokens,
                output_tokens=ctx.output_tokens,
                total_cost_usd=ctx.gen_cost,
            )

    async def _persist_generated_answer(self, ctx: QueryContext) -> UUID:
        assert ctx.query_session_id is not None
        prompt_version_id = (
            ctx.resolved_prompt.id if ctx.resolved_prompt is not None else None
        )
        model_provider = (
            ctx.effective_model.split("/", 1)[0]
            if "/" in ctx.effective_model
            else "unknown"
        )
        return await self._answers.create(
            tenant_id=ctx.auth.tenant_id,
            query_session_id=ctx.query_session_id,
            answer_text=ctx.answer_text,
            model_provider=model_provider,
            model_name=ctx.effective_model,
            prompt_version_id=prompt_version_id,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
            cost_usd=ctx.gen_cost,
            grounding_score=ctx.grounding_score,
            nli_verdict=ctx.nli_verdict,
            judge_verdict=ctx.judge_verdict,
            judge_reasoning=ctx.judge_reasoning,
        )

    async def _persist_citations(self, ctx: QueryContext) -> list[CitationOut]:
        assert ctx.generated_answer_id is not None
        referenced = set(referenced_indices(ctx.answer_text))
        out: list[CitationOut] = []
        for idx, cand in ctx.citations_for_persist:
            if referenced and idx not in referenced:
                continue
            citation_id = await self._citations.create(
                tenant_id=ctx.auth.tenant_id,
                generated_answer_id=ctx.generated_answer_id,
                chunk_id=cand.chunk_id,
                citation_index=idx,
                quoted_text=cand.content[:500],
                relevance_score=cand.score,
            )
            out.append(
                CitationOut(
                    citation_id=citation_id,
                    chunk_id=cand.chunk_id,
                    document_id=cand.document_id,
                    citation_index=idx,
                    quoted_text=cand.content[:500],
                    page_number=cand.page_number,
                    section_title=cand.section_title,
                    relevance_score=cand.score,
                )
            )
        return out
