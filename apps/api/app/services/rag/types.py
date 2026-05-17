"""Configs, result types, and the mutable ``QueryContext`` passed between stages."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sentinelrag_shared.auth import AuthContext
    from sentinelrag_shared.llm import LiteLLMEmbedder, UsageRecord
    from sentinelrag_shared.retrieval import Candidate, HybridRetrievalResult

    from app.db.models import PromptVersion
    from app.services.cost_service import BudgetDecision


@dataclass(slots=True)
class RetrievalConfig:
    mode: str = "hybrid"
    top_k_bm25: int = 20
    top_k_vector: int = 20
    top_k_hybrid: int = 30
    top_k_rerank: int = 8
    ef_search: int | None = None


@dataclass(slots=True)
class GenerationConfig:
    model: str = "ollama/llama3.1:8b"
    temperature: float = 0.1
    max_tokens: int = 800


@dataclass(slots=True)
class QueryOptions:
    include_debug_trace: bool = False
    abstain_if_unsupported: bool = True
    prompt_version_id: UUID | None = None


@dataclass(slots=True)
class CitationOut:
    citation_id: UUID
    chunk_id: UUID
    document_id: UUID
    citation_index: int
    quoted_text: str | None
    page_number: int | None
    section_title: str | None
    relevance_score: float | None


@dataclass(slots=True)
class QueryResult:
    query_session_id: UUID
    answer: str
    confidence_score: float | None
    grounding_score: float | None
    hallucination_risk_score: float | None
    nli_verdict: str | None
    judge_verdict: str | None
    citations: list[CitationOut]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


# Sentinel used when retrieval returns no candidates and the caller opted in
# to abstention. Kept module-level so tests can import the same string the
# generation stage emits.
ABSTAIN_ANSWER = (
    "I do not have enough information in the provided sources "
    "to answer that confidently."
)


@dataclass(slots=True)
class QueryContext:
    """Mutable state container passed through every stage.

    Inputs are set at construction. Stages mutate the post-input fields as
    the pipeline progresses. Compose into a ``QueryResult`` at the end.
    """

    # --- Inputs (immutable for the run) ---
    query: str
    auth: AuthContext
    collection_ids: list[UUID]
    retrieval_cfg: RetrievalConfig
    generation_cfg: GenerationConfig
    options: QueryOptions
    embedder: LiteLLMEmbedder
    ollama_base_url: str
    start_time: float = field(default_factory=time.perf_counter)

    # --- Retrieval ---
    query_session_id: UUID | None = None
    hybrid_result: HybridRetrievalResult | None = None
    reranked: list[Candidate] = field(default_factory=list)

    # --- Context + prompt ---
    context_text: str = ""
    citations_for_persist: list[tuple[int, Candidate]] = field(default_factory=list)
    resolved_prompt: PromptVersion | None = None

    # --- Budget + generation ---
    budget_decision: BudgetDecision | None = None
    effective_model: str = ""
    answer_text: str = ""
    gen_usage: UsageRecord | None = None
    gen_cost: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0

    # --- Quality signals (ADR-0010 layered cascade) ---
    grounding_score: float | None = None
    nli_verdict: str | None = None
    judge_verdict: str | None = None
    judge_reasoning: str | None = None

    # --- Persistence outputs ---
    generated_answer_id: UUID | None = None
    cited_out: list[CitationOut] = field(default_factory=list)

    # --- Final ---
    latency_ms: int = 0

    def to_query_result(self) -> QueryResult:
        if self.query_session_id is None:
            msg = "QueryContext has no query_session_id; SessionStage.open() must run first."
            raise RuntimeError(msg)
        return QueryResult(
            query_session_id=self.query_session_id,
            answer=self.answer_text,
            confidence_score=None,
            grounding_score=self.grounding_score,
            hallucination_risk_score=None,
            nli_verdict=self.nli_verdict,
            judge_verdict=self.judge_verdict,
            citations=self.cited_out,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=float(self.gen_cost),
            latency_ms=self.latency_ms,
        )
