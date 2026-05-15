"""Cross-service contracts for the retrieval-service diagnostic wrapper."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from sentinelrag_shared.contracts.base import Contract


class RetrievalCandidateInput(Contract):
    chunk_id: UUID
    document_id: UUID
    content: str = Field(..., min_length=1)
    score: float
    rank: int = Field(..., ge=1)
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RetrievalCandidateOutput(RetrievalCandidateInput):
    stage: str


class RrfMergeRequest(Contract):
    bm25: list[RetrievalCandidateInput] = Field(default_factory=list)
    vector: list[RetrievalCandidateInput] = Field(default_factory=list)
    top_k: int = Field(default=30, ge=0, le=200)
    rrf_k: int = Field(default=60, ge=1, le=500)


class RrfMergeResponse(Contract):
    candidates: list[RetrievalCandidateOutput]


class RetrievalCapabilitiesResponse(Contract):
    service_role: str = "diagnostic-wrapper"
    modes: list[str] = Field(default_factory=lambda: ["rrf_merge"])
    stages: list[str]
    endpoints: list[str] = Field(default_factory=lambda: ["/rrf-merge"])
    rrf: bool = True
    retrieval_backends: list[str] = Field(default_factory=list)
    rbac_at_retrieval_time: bool = False
