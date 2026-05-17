"""GroundingStage — quality signal on the answer.

R1: token-overlap layer only (cheap, always on). R2 stacks NLI + LLM-judge
sample on top behind Unleash flags.
"""

from __future__ import annotations

from app.services.rag._helpers import token_overlap_score
from app.services.rag.types import QueryContext


class GroundingStage:
    async def run(self, ctx: QueryContext) -> None:
        ctx.grounding_score = token_overlap_score(ctx.answer_text, ctx.context_text)
