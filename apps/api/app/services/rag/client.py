"""RetrievalClient — the seam between the orchestrator and retrieval backend.

Two impls live behind the :class:`RetrievalClient` Protocol:

- :class:`InProcessRetrievalClient` (R1.S1): composes
  ``PostgresFtsKeywordSearch`` + ``PgvectorVectorSearch`` +
  ``HybridRetriever`` directly against the API's SQLAlchemy session.
- :class:`HttpRetrievalClient` (R4.S2): POSTs to
  ``apps/retrieval-service`` over httpx with OTel context propagation
  and retry-with-backoff on 5xx.

Selection is owned by ``apps/api/app/lifecycle.py`` via the
``RETRIEVAL_MODE`` setting (R4.S3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

import httpx
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.contracts import (
    AuthContextDTO,
    EmbeddingUsageDTO,
    RetrievalCandidateOutput,
    RetrieveRequest,
    RetrieveResponse,
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
)
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.services.rag._helpers import restage_candidates


class RetrievalClientError(Exception):
    """Raised by HttpRetrievalClient when the remote call fails permanently."""


class _PrecomputedEmbedder:
    """Single-use embedder that replays a precomputed :class:`EmbeddingResult`.

    Used by :class:`InProcessRetrievalClient` so the query embedding is
    paid for exactly once per request, even though ``PgvectorVectorSearch``
    expects an :class:`Embedder` that can ``await embedder.embed([query])``
    itself. Exposing token/cost usage from the inner embedder up to the
    orchestrator (for budget accounting + persistence) is the point.
    """

    def __init__(self, *, model_name: str, dimension: int, result: EmbeddingResult) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self._result = result

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if len(texts) != 1:
            msg = (
                "_PrecomputedEmbedder only supports the single-query retrieval "
                f"path; got {len(texts)} texts."
            )
            raise RuntimeError(msg)
        return self._result


class RetrievalClient(Protocol):
    """Async contract a RAG retrieval backend must satisfy.

    ``mode`` is one of ``"bm25"``, ``"vector"``, or ``"hybrid"``. The
    implementation dispatches to the right backend(s) and returns the unified
    ``HybridRetrievalResult`` shape so the orchestrator persists the same
    stage-tagged rows regardless of mode.
    """

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        mode: str,
        top_k_bm25: int,
        top_k_vector: int,
        top_k_hybrid: int,
        ef_search: int | None,
    ) -> HybridRetrievalResult: ...


class InProcessRetrievalClient:
    """In-process implementation — calls the shared retrieval library directly.

    Per-request construction is preserved here to match v1 behavior; R3.S6
    hoists embedder + session to ``app.state`` and DIs them in.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedder: LiteLLMEmbedder,
        access_filter: AccessFilter | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._access_filter = access_filter or AccessFilter()

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        mode: str,
        top_k_bm25: int,
        top_k_vector: int,
        top_k_hybrid: int,
        ef_search: int | None,
    ) -> HybridRetrievalResult:
        keyword_search = PostgresFtsKeywordSearch(
            session=self._session, access_filter=self._access_filter
        )

        # bm25-only never needs the embedder.
        if mode == "bm25":
            bm25 = await keyword_search.search(
                query=query,
                auth=auth,
                collection_ids=collection_ids,
                top_k=top_k_bm25,
            )
            return HybridRetrievalResult(
                bm25_candidates=bm25,
                vector_candidates=[],
                merged_candidates=restage_candidates(
                    bm25[:top_k_hybrid], RetrievalStage.HYBRID_MERGE
                ),
            )

        # Vector or hybrid: embed the query once here so the resulting
        # usage record can flow up to the orchestrator for budget +
        # persistence (R3.S1). PgvectorVectorSearch then replays the
        # cached vector via _PrecomputedEmbedder.
        embedding_result = await self._embedder.embed([query])
        vector_embedder = _PrecomputedEmbedder(
            model_name=self._embedder.model_name,
            dimension=self._embedder.dimension,
            result=embedding_result,
        )
        vector_search = PgvectorVectorSearch(
            session=self._session,
            embedder=vector_embedder,
            access_filter=self._access_filter,
        )

        if mode == "vector":
            vector = await vector_search.search(
                query=query,
                auth=auth,
                collection_ids=collection_ids,
                top_k=top_k_vector,
                ef_search=ef_search,
            )
            return HybridRetrievalResult(
                bm25_candidates=[],
                vector_candidates=vector,
                merged_candidates=restage_candidates(
                    vector[:top_k_hybrid], RetrievalStage.HYBRID_MERGE
                ),
                embedding_usage=embedding_result.usage,
            )

        hybrid = HybridRetriever(
            keyword_search=keyword_search,
            vector_search=vector_search,
        )
        result = await hybrid.retrieve(
            query=query,
            auth=auth,
            collection_ids=collection_ids,
            top_k_bm25=top_k_bm25,
            top_k_vector=top_k_vector,
            top_k_hybrid=top_k_hybrid,
            ef_search=ef_search,
        )
        result.embedding_usage = embedding_result.usage
        return result


class HttpRetrievalClient:
    """RetrievalClient that POSTs to ``apps/retrieval-service`` (R4.S2).

    Args:
        base_url: ``http(s)://retrieval:8000`` — DNS resolves to the
            in-cluster Service in deployed environments.
        service_token: shared bearer token sent in the ``Authorization``
            header. The retrieval-service verifies it against its own
            copy of the same secret (R4 v1 service-to-service auth;
            the ADR documents the mTLS / Keycloak-service-account
            upgrade path).
        client: optional shared httpx AsyncClient. When ``None`` we
            build one with ``http2=True`` and a connection-pool size
            matched to the API's worker count.
        timeout_seconds: per-call wall-clock cap (default 5s). On
            timeout the retry policy fires; after the retry budget is
            exhausted :class:`RetrievalClientError` is raised.
        max_retries: total attempts including the first. Only
            ``502/503/504`` and transient connection errors retry —
            ``4xx`` responses short-circuit immediately so a bug on the
            API side surfaces fast instead of being smeared across
            three retries.
    """

    _RETRYABLE_STATUS = frozenset({502, 503, 504})

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._owned_client = client is None
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            http2=False,  # local dev MinIO etc. may not negotiate h2 cleanly
            headers={"User-Agent": "sentinelrag-api/HttpRetrievalClient"},
        )

    async def aclose(self) -> None:
        """Release the underlying connection pool when this client built it."""
        if self._owned_client:
            await self._client.aclose()

    async def retrieve(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID],
        mode: str,
        top_k_bm25: int,
        top_k_vector: int,
        top_k_hybrid: int,
        ef_search: int | None,
    ) -> HybridRetrievalResult:
        if mode not in {"bm25", "vector", "hybrid"}:
            msg = f"HttpRetrievalClient: unsupported mode {mode!r}."
            raise RetrievalClientError(msg)

        request = RetrieveRequest(
            query=query,
            auth=AuthContextDTO(
                user_id=auth.user_id,
                tenant_id=auth.tenant_id,
                email=auth.email,
                permissions=sorted(auth.permissions),
            ),
            collection_ids=collection_ids,
            mode=mode,  # type: ignore[arg-type]
            top_k_bm25=top_k_bm25,
            top_k_vector=top_k_vector,
            top_k_hybrid=top_k_hybrid,
            ef_search=ef_search,
        )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.2, min=0.2, max=2.0),
                retry=retry_if_exception_type(_RetryableRetrievalError),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.post(
                        "/v1/retrieve",
                        json=request.model_dump(mode="json"),
                        headers={
                            "Authorization": f"Bearer {self._service_token}",
                        },
                    )
                    if response.status_code in self._RETRYABLE_STATUS:
                        msg = (
                            f"retrieval-service returned {response.status_code}; "
                            "retryable."
                        )
                        raise _RetryableRetrievalError(msg)
                    response.raise_for_status()
                    break
            else:
                msg = "HttpRetrievalClient: AsyncRetrying produced no result."
                raise RetrievalClientError(msg)
        except _RetryableRetrievalError as exc:
            msg = f"retrieval-service exhausted retries: {exc}"
            raise RetrievalClientError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = (
                f"retrieval-service {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            raise RetrievalClientError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"retrieval-service unreachable: {exc!r}"
            raise RetrievalClientError(msg) from exc

        parsed = RetrieveResponse.model_validate(response.json())
        return _to_hybrid_result(parsed)


class _RetryableRetrievalError(Exception):
    """Internal — used by tenacity to mark 5xx + network blips for retry."""


def _to_hybrid_result(payload: RetrieveResponse) -> HybridRetrievalResult:
    """Re-hydrate a wire-format ``RetrieveResponse`` to the in-process shape."""
    return HybridRetrievalResult(
        bm25_candidates=[_candidate_from_dto(c) for c in payload.bm25_candidates],
        vector_candidates=[_candidate_from_dto(c) for c in payload.vector_candidates],
        merged_candidates=[
            _candidate_from_dto(c) for c in payload.merged_candidates
        ],
        metadata=dict(payload.metadata),
        embedding_usage=_usage_from_dto(payload.embedding_usage),
    )


def _candidate_from_dto(dto: RetrievalCandidateOutput) -> Candidate:
    return Candidate(
        chunk_id=dto.chunk_id,
        document_id=dto.document_id,
        content=dto.content,
        score=dto.score,
        rank=dto.rank,
        stage=RetrievalStage(dto.stage),
        page_number=dto.page_number,
        section_title=dto.section_title,
        metadata=dict(dto.metadata),
    )


def _usage_from_dto(dto: EmbeddingUsageDTO | None) -> UsageRecord | None:
    if dto is None:
        return None
    return UsageRecord(
        usage_type="embedding",
        provider=dto.provider,
        model_name=dto.model_name,
        input_tokens=dto.input_tokens,
        output_tokens=dto.output_tokens,
        total_cost_usd=dto.total_cost_usd,
        latency_ms=dto.latency_ms,
    )


