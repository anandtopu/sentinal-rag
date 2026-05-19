"""Cross-service contracts for the retrieval-service.

Two contract families live here:

1. **Live retrieval** (R4): the request/response models the API service
   sends to ``apps/retrieval-service`` over HTTP when
   ``RETRIEVAL_MODE=http``. These mirror the ``RetrievalClient`` Protocol
   shape exactly so the in-process and HTTP impls are wire-compatible.

2. **Diagnostic wrapper** (pre-R4): the ``Rrf*`` and ``RetrievalCapabilities``
   models that the old diagnostic-only service exposes. Kept for backward
   compatibility — the retrieval-service still serves them — but new
   callers should use the live retrieval shape.

Versioning is path-based on the service side (``/v1/retrieve``). Adding
a field is backward compatible because :class:`Contract` enforces
``extra='forbid'`` but the FastAPI client sends only declared fields.
Renaming or removing a field requires a parallel ``/v2/retrieve``
deployment + a deprecation window for the older path.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
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
    modes: list[str] = Field(default_factory=lambda: ["rrf_merge", "retrieve"])
    stages: list[str]
    endpoints: list[str] = Field(
        default_factory=lambda: ["/rrf-merge", "/v1/retrieve"]
    )
    rrf: bool = True
    retrieval_backends: list[str] = Field(default_factory=list)
    rbac_at_retrieval_time: bool = False


# --- Live retrieval (R4) ---------------------------------------------------


class AuthContextDTO(Contract):
    """Serialized :class:`sentinelrag_shared.auth.AuthContext`.

    Cross-service calls preserve identity end-to-end so RBAC at retrieval
    time (architecture pillar #1) survives the network hop. ``permissions``
    is a sorted list on the wire to keep request payloads diffable in
    audit logs.
    """

    user_id: UUID
    tenant_id: UUID
    email: str
    permissions: list[str] = Field(default_factory=list)


class RetrieveRequest(Contract):
    """Request envelope for ``POST /v1/retrieve``.

    Mirrors the :class:`RetrievalClient` Protocol arguments. ``mode`` is a
    closed enum so a typo on the API side surfaces as a 422 not a
    semantic miss.
    """

    query: str = Field(..., min_length=1)
    auth: AuthContextDTO
    collection_ids: list[UUID] = Field(default_factory=list)
    mode: Literal["bm25", "vector", "hybrid"]
    top_k_bm25: int = Field(default=20, ge=1, le=200)
    top_k_vector: int = Field(default=20, ge=1, le=200)
    top_k_hybrid: int = Field(default=30, ge=1, le=200)
    ef_search: int | None = Field(default=None, ge=1, le=512)


class EmbeddingUsageDTO(Contract):
    """Subset of ``UsageRecord`` carried in the retrieval response.

    The retrieval-service computes the query embedding on its side and
    reports the cost/tokens back so the API's budget gate + persistence
    stage can include it (R3.S1). ``total_cost_usd`` is a Decimal on the
    wire to avoid float drift; clients re-hydrate to ``Decimal`` on read.
    """

    provider: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: Decimal | None = None
    latency_ms: int | None = None


class RetrieveResponse(Contract):
    """Response envelope for ``POST /v1/retrieve``.

    Field-for-field the serialized form of
    :class:`HybridRetrievalResult`. ``embedding_usage`` is ``None`` on a
    bm25-only request — that path never calls the embedder, matching the
    in-process behavior.
    """

    bm25_candidates: list[RetrievalCandidateOutput] = Field(default_factory=list)
    vector_candidates: list[RetrievalCandidateOutput] = Field(default_factory=list)
    merged_candidates: list[RetrievalCandidateOutput] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    embedding_usage: EmbeddingUsageDTO | None = None
