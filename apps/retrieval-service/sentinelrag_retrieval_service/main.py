"""FastAPI app for the retrieval-service.

Two route families:

- **Diagnostic** (pre-R4): ``/health``, ``/capabilities``, ``/rrf-merge``
  — kept for backward compatibility with the original shell-service
  contract.
- **Live retrieval** (R4): ``/v1/retrieve`` — the real BM25 / vector /
  hybrid search behind a service-to-service bearer token. Reconstructs
  an ``AuthContext`` from the request body so RBAC at retrieval time
  (architecture pillar #1) survives the network hop.

Per ADR-0009 / R4.S7 the cross-service contract is REST + Pydantic v2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.contracts import (
    AuthContextDTO,
    EmbeddingUsageDTO,
    RetrievalCandidateInput,
    RetrievalCandidateOutput,
    RetrievalCapabilitiesResponse,
    RetrieveRequest,
    RetrieveResponse,
    RrfMergeRequest,
    RrfMergeResponse,
)
from sentinelrag_shared.llm import EmbeddingResult, LiteLLMEmbedder, UsageRecord
from sentinelrag_shared.retrieval import (
    AccessFilter,
    Candidate,
    HybridRetrievalResult,
    HybridRetriever,
    PgvectorVectorSearch,
    PostgresFtsKeywordSearch,
    RetrievalStage,
    merge_with_rrf,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelrag_retrieval_service.config import Settings, get_settings
from sentinelrag_retrieval_service.db import (
    dispose_engine,
    get_session_factory,
    open_tenant_session,
)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "sentinelrag-retrieval-service"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Pre-warm the session factory; tear the engine down cleanly."""
    del app
    # Touching the factory builds the engine. We don't open a probe
    # connection here — the request path is the source of truth, and a
    # bad DSN should surface on the first call rather than block
    # startup.
    get_session_factory()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(
    title="SentinelRAG Retrieval Service",
    version="0.1.0",
    description=(
        "Real BM25 / vector / hybrid retrieval behind a service-to-service "
        "bearer token. Mirrors apps/api's RetrievalClient Protocol shape."
    ),
    lifespan=lifespan,
)


# --- Diagnostic endpoints (unchanged from the v0 shell) -------------------


@app.get("/health", response_model=HealthResponse)
@app.get("/healthz", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/capabilities", response_model=RetrievalCapabilitiesResponse)
async def capabilities(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RetrievalCapabilitiesResponse:
    return RetrievalCapabilitiesResponse(
        service_role="real-retrieval",
        modes=["bm25", "vector", "hybrid", "rrf_merge"],
        stages=[stage.value for stage in RetrievalStage],
        endpoints=["/rrf-merge", "/v1/retrieve"],
        retrieval_backends=["postgres_fts", "pgvector_hnsw"],
        rbac_at_retrieval_time=True,
        rrf=True,
    ) if settings.service_token else RetrievalCapabilitiesResponse(
        # Without a service token configured we expose the diagnostic
        # surface only — refuse to advertise capabilities we'd refuse
        # to serve.
        service_role="diagnostic-wrapper",
        modes=["rrf_merge"],
        stages=[stage.value for stage in RetrievalStage],
        endpoints=["/rrf-merge"],
        retrieval_backends=[],
        rbac_at_retrieval_time=False,
        rrf=True,
    )


@app.post("/rrf-merge", response_model=RrfMergeResponse)
async def rrf_merge(payload: RrfMergeRequest) -> RrfMergeResponse:
    merged = merge_with_rrf(
        bm25=[_to_candidate(c, RetrievalStage.BM25) for c in payload.bm25],
        vector=[_to_candidate(c, RetrievalStage.VECTOR) for c in payload.vector],
        top_k=payload.top_k,
        rrf_k=payload.rrf_k,
    )
    return RrfMergeResponse(candidates=[_to_out(c) for c in merged])


def _to_candidate(raw: RetrievalCandidateInput, stage: RetrievalStage) -> Candidate:
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


def _to_out(candidate: Candidate) -> RetrievalCandidateOutput:
    return RetrievalCandidateOutput(
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


# --- Service-to-service auth ---------------------------------------------


def require_service_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    """Verify the ``Authorization: Bearer <token>`` header.

    The retrieval-service is a closed surface — only the API service
    talks to it. We refuse with 503 when no token is configured so an
    accidentally-public deploy fails loud rather than silently exposing
    retrieval to unauthenticated callers.
    """
    if not settings.service_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retrieval-service: SERVICE_TOKEN not configured.",
        )
    expected = f"Bearer {settings.service_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service bearer token.",
        )


# --- Live retrieval (R4.S4) -----------------------------------------------


@app.post(
    "/v1/retrieve",
    response_model=RetrieveResponse,
    dependencies=[Depends(require_service_token)],
)
async def retrieve(payload: RetrieveRequest) -> RetrieveResponse:
    """Run the same hybrid pipeline the API used to run in-process.

    The body carries the resolved ``AuthContext`` — we trust it because
    the bearer token guard above already established that the caller is
    the API service. Cross-tenant data leakage is still prevented by
    the Postgres RLS bound on the session for this request.
    """
    settings = get_settings()
    auth = _auth_from_dto(payload.auth)

    # Hybrid mode + vector mode both need the embedding. bm25 mode
    # does not — preserve the API-side behavior where embedding cost
    # is None for bm25-only queries.
    embedding_result: EmbeddingResult | None = None
    embedder: LiteLLMEmbedder | None = None
    if payload.mode != "bm25":
        embedder = LiteLLMEmbedder(
            model_name=settings.default_embedding_model,
            api_base=settings.ollama_base_url
            if settings.default_embedding_model.startswith("ollama/")
            else None,
        )
        embedding_result = await embedder.embed([payload.query])

    async for session in open_tenant_session(payload.auth.tenant_id):
        return await _run_retrieval(
            session=session,
            auth=auth,
            payload=payload,
            embedder=embedder,
            embedding_result=embedding_result,
        )
    # The generator must yield exactly once; if we get here something
    # is structurally wrong.
    msg = "open_tenant_session yielded nothing."
    raise RuntimeError(msg)


async def _run_retrieval(
    *,
    session: AsyncSession,
    auth: AuthContext,
    payload: RetrieveRequest,
    embedder: LiteLLMEmbedder | None,
    embedding_result: EmbeddingResult | None,
) -> RetrieveResponse:
    access_filter = AccessFilter()
    keyword_search = PostgresFtsKeywordSearch(
        session=session, access_filter=access_filter
    )

    if payload.mode == "bm25":
        bm25 = await keyword_search.search(
            query=payload.query,
            auth=auth,
            collection_ids=list(payload.collection_ids),
            top_k=payload.top_k_bm25,
        )
        merged = _restage(bm25[: payload.top_k_hybrid], RetrievalStage.HYBRID_MERGE)
        return _build_response(
            bm25_candidates=bm25,
            vector_candidates=[],
            merged_candidates=merged,
            metadata={"mode": "bm25"},
            embedding_usage=None,
        )

    # vector + hybrid both need vector_search wired with a single-use
    # embedder that replays the precomputed query vector.
    assert embedder is not None
    assert embedding_result is not None
    vector_embedder = _PrecomputedEmbedder(
        model_name=embedder.model_name,
        dimension=embedder.dimension,
        result=embedding_result,
    )
    vector_search = PgvectorVectorSearch(
        session=session, embedder=vector_embedder, access_filter=access_filter
    )

    if payload.mode == "vector":
        vector = await vector_search.search(
            query=payload.query,
            auth=auth,
            collection_ids=list(payload.collection_ids),
            top_k=payload.top_k_vector,
            ef_search=payload.ef_search,
        )
        merged = _restage(
            vector[: payload.top_k_hybrid], RetrievalStage.HYBRID_MERGE
        )
        return _build_response(
            bm25_candidates=[],
            vector_candidates=vector,
            merged_candidates=merged,
            metadata={"mode": "vector"},
            embedding_usage=embedding_result.usage,
        )

    hybrid = HybridRetriever(
        keyword_search=keyword_search, vector_search=vector_search
    )
    result: HybridRetrievalResult = await hybrid.retrieve(
        query=payload.query,
        auth=auth,
        collection_ids=list(payload.collection_ids),
        top_k_bm25=payload.top_k_bm25,
        top_k_vector=payload.top_k_vector,
        top_k_hybrid=payload.top_k_hybrid,
        ef_search=payload.ef_search,
    )
    return _build_response(
        bm25_candidates=result.bm25_candidates,
        vector_candidates=result.vector_candidates,
        merged_candidates=result.merged_candidates,
        metadata=result.metadata,
        embedding_usage=embedding_result.usage,
    )


def _build_response(
    *,
    bm25_candidates: list[Candidate],
    vector_candidates: list[Candidate],
    merged_candidates: list[Candidate],
    metadata: dict[str, object],
    embedding_usage: UsageRecord | None,
) -> RetrieveResponse:
    return RetrieveResponse(
        bm25_candidates=[_to_out(c) for c in bm25_candidates],
        vector_candidates=[_to_out(c) for c in vector_candidates],
        merged_candidates=[_to_out(c) for c in merged_candidates],
        metadata=dict(metadata),
        embedding_usage=_usage_to_dto(embedding_usage),
    )


def _restage(candidates: list[Candidate], stage: RetrievalStage) -> list[Candidate]:
    return [
        Candidate(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            content=c.content,
            score=c.score,
            rank=rank,
            stage=stage,
            page_number=c.page_number,
            section_title=c.section_title,
            metadata=dict(c.metadata),
        )
        for rank, c in enumerate(candidates, start=1)
    ]


def _auth_from_dto(dto: AuthContextDTO) -> AuthContext:
    return AuthContext(
        user_id=dto.user_id,
        tenant_id=dto.tenant_id,
        email=dto.email,
        permissions=frozenset(dto.permissions),
    )


def _usage_to_dto(usage: UsageRecord | None) -> EmbeddingUsageDTO | None:
    if usage is None:
        return None
    return EmbeddingUsageDTO(
        provider=usage.provider,
        model_name=usage.model_name,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_cost_usd=usage.total_cost_usd if usage.total_cost_usd is not None else None,
        latency_ms=usage.latency_ms,
    )


# Re-import the precomputed-embedder shim from the API service's
# retrieval client. Duplicating the small class here keeps the
# retrieval-service free of an apps/api import (which would create a
# cycle); kept in sync via the structural protocol the embedder
# satisfies.
class _PrecomputedEmbedder:
    def __init__(
        self,
        *,
        model_name: str,
        dimension: int,
        result: EmbeddingResult,
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self._result = result

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if len(texts) != 1:
            msg = (
                "_PrecomputedEmbedder only supports the single-query retrieval "
                f"path; got {len(texts)} texts."
            )
            raise RuntimeError(msg)
        return self._result


