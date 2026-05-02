"""Pydantic schemas for /query and /query/{id}/trace.

Mirrors Enterprise_RAG_Database_Design.md §19. The schema names use ``snake_case``
to match the rest of the API; the field names match the spec's JSON example.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel


class RetrievalConfigIn(APIModel):
    mode: Literal["hybrid", "bm25", "vector"] = Field(default="hybrid")
    top_k_bm25: int = Field(default=20, ge=1, le=200)
    top_k_vector: int = Field(default=20, ge=1, le=200)
    top_k_hybrid: int = Field(default=30, ge=1, le=200)
    top_k_rerank: int = Field(default=8, ge=0, le=50)
    ef_search: int | None = Field(default=None, ge=1, le=512)


class GenerationConfigIn(APIModel):
    model: str | None = Field(default=None)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=1, le=8192)


class QueryOptionsIn(APIModel):
    include_citations: bool = True
    include_debug_trace: bool = False
    abstain_if_unsupported: bool = True


class QueryRequest(APIModel):
    query: str = Field(..., min_length=1, max_length=4000)
    collection_ids: list[UUID] = Field(..., min_length=1, max_length=20)
    retrieval: RetrievalConfigIn = Field(default_factory=RetrievalConfigIn)
    generation: GenerationConfigIn = Field(default_factory=GenerationConfigIn)
    options: QueryOptionsIn = Field(default_factory=QueryOptionsIn)


class CitationRead(APIModel):
    citation_id: UUID
    document_id: UUID
    chunk_id: UUID
    citation_index: int
    page_number: int | None
    section_title: str | None
    quoted_text: str | None
    relevance_score: float | None


class QueryUsage(APIModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class QueryResponse(APIModel):
    query_session_id: UUID
    answer: str
    confidence_score: float | None
    grounding_score: float | None
    hallucination_risk_score: float | None
    citations: list[CitationRead]
    usage: QueryUsage


# ---- Trace ----


class RetrievalResultRead(APIModel):
    chunk_id: UUID
    stage: str
    rank: int
    score: float
    metadata: dict[str, Any]


class GeneratedAnswerSummary(APIModel):
    model: str
    prompt_version_id: UUID | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    grounding_score: float | None
    hallucination_risk_score: float | None
    confidence_score: float | None


class QueryTraceResponse(APIModel):
    query_session_id: UUID
    query: str
    status: str
    latency_ms: int | None
    created_at: datetime
    retrieval_results: list[RetrievalResultRead]
    generation: GeneratedAnswerSummary | None
