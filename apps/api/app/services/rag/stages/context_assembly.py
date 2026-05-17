"""ContextAssemblyStage — build the numbered context block + citation map.

Pure logic, no IO.
"""

from __future__ import annotations

from sentinelrag_shared.retrieval import Candidate

from app.services.rag.types import QueryContext


class ContextAssemblyStage:
    async def run(self, ctx: QueryContext) -> None:
        ctx.context_text, ctx.citations_for_persist = self._assemble(ctx.reranked)

    @staticmethod
    def _assemble(
        reranked: list[Candidate],
    ) -> tuple[str, list[tuple[int, Candidate]]]:
        lines: list[str] = []
        citations: list[tuple[int, Candidate]] = []
        for i, cand in enumerate(reranked, start=1):
            page = (
                f", page {cand.page_number}" if cand.page_number is not None else ""
            )
            section = f" — {cand.section_title}" if cand.section_title else ""
            lines.append(f"[{i}{section}{page}] {cand.content}")
            citations.append((i, cand))
        return "\n\n".join(lines), citations
