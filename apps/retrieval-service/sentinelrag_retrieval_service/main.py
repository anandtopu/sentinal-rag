"""FastAPI app for standalone retrieval primitives.

Retrieval runs in-process inside the API for v1 (ADR-0021). This service is a
thin, runnable wrapper around the shared retrieval library so the workspace
package and local `make retrieval` target are honest and do not collide with
the API's top-level ``app`` package.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sentinelrag_shared.retrieval import Candidate, RetrievalStage, merge_with_rrf


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "sentinelrag-retrieval-service"


class CandidateIn(BaseModel):
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float
    rank: int = Field(..., ge=1)
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CandidateOut(CandidateIn):
    stage: str


class RrfMergeRequest(BaseModel):
    bm25: list[CandidateIn] = Field(default_factory=list)
    vector: list[CandidateIn] = Field(default_factory=list)
    top_k: int = Field(default=30, ge=0, le=200)
    rrf_k: int = Field(default=60, ge=1, le=500)


class RrfMergeResponse(BaseModel):
    candidates: list[CandidateOut]


app = FastAPI(
    title="SentinelRAG Retrieval Service",
    version="0.1.0",
    description="Thin wrapper around shared retrieval primitives.",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/capabilities", response_model=dict[str, object])
async def capabilities() -> dict[str, object]:
    return {
        "service_role": "diagnostic-wrapper",
        "modes": ["rrf_merge"],
        "stages": [stage.value for stage in RetrievalStage],
        "endpoints": ["/rrf-merge"],
        "rrf": True,
        "retrieval_backends": [],
        "rbac_at_retrieval_time": False,
    }


@app.post("/rrf-merge", response_model=RrfMergeResponse)
async def rrf_merge(payload: RrfMergeRequest) -> RrfMergeResponse:
    merged = merge_with_rrf(
        bm25=[_to_candidate(c, RetrievalStage.BM25) for c in payload.bm25],
        vector=[_to_candidate(c, RetrievalStage.VECTOR) for c in payload.vector],
        top_k=payload.top_k,
        rrf_k=payload.rrf_k,
    )
    return RrfMergeResponse(candidates=[_to_out(c) for c in merged])


def _to_candidate(raw: CandidateIn, stage: RetrievalStage) -> Candidate:
    return Candidate(
        chunk_id=raw.chunk_id,
        document_id=raw.document_id,
        content=raw.content,
        score=raw.score,
        rank=raw.rank,
        stage=stage,
        page_number=raw.page_number,
        section_title=raw.section_title,
        metadata=dict(raw.metadata),
    )


def _to_out(candidate: Candidate) -> CandidateOut:
    return CandidateOut(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        content=candidate.content,
        score=candidate.score,
        rank=candidate.rank,
        stage=candidate.stage.value,
        page_number=candidate.page_number,
        section_title=candidate.section_title,
        metadata=candidate.metadata,
    )
