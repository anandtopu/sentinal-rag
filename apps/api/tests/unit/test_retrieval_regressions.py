"""Regression tests for retrieval configuration and shared retriever behavior."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from app.schemas.query import RetrievalConfigIn
from pydantic import ValidationError
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.llm.types import EmbeddingResult, UsageRecord
from sentinelrag_shared.retrieval import (
    AccessFilter,
    Candidate,
    HybridRetriever,
    PgvectorVectorSearch,
    PostgresFtsKeywordSearch,
    RetrievalStage,
    merge_with_rrf,
)
from sentinelrag_shared.retrieval.vector_search import VectorSearchError, _format_vector


def _auth() -> AuthContext:
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        email="demo@example.com",
        permissions=frozenset({"queries:execute"}),
    )


def _candidate(
    stage: RetrievalStage, rank: int = 1, *, chunk_id: UUID | None = None
) -> Candidate:
    return Candidate(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        content="hnsw ef search tuning",
        score=1.0,
        rank=rank,
        stage=stage,
    )


class FakeKeywordSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> list[Candidate]:
        self.calls.append(kwargs)
        return [_candidate(RetrievalStage.BM25)]


class FakeVectorSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> list[Candidate]:
        self.calls.append(kwargs)
        return [_candidate(RetrievalStage.VECTOR)]


class FakeSqlResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[Any]:
        return self.rows


class FakeSqlSession:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, statement: object, params: dict[str, Any] | None = None
    ) -> FakeSqlResult:
        self.calls.append((str(statement), dict(params or {})))
        return FakeSqlResult(self.rows)


class FakeEmbedder:
    model_name = "ollama/nomic-embed-text"
    dimension = 768

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3]] if texts else [],
            model_name=self.model_name,
            dimension=self.dimension,
            usage=UsageRecord(
                usage_type="embedding",
                provider="ollama",
                model_name=self.model_name,
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hybrid_retriever_forwards_ef_search_to_vector_arm() -> None:
    keyword = FakeKeywordSearch()
    vector = FakeVectorSearch()
    retriever = HybridRetriever(keyword_search=keyword, vector_search=vector)

    await retriever.retrieve(
        query="what is hnsw ef_search?",
        auth=_auth(),
        collection_ids=[uuid4()],
        top_k_bm25=3,
        top_k_vector=4,
        top_k_hybrid=5,
        ef_search=128,
    )

    assert keyword.calls[0]["top_k"] == 3
    assert vector.calls[0]["top_k"] == 4
    assert vector.calls[0]["ef_search"] == 128


@pytest.mark.unit
def test_query_retrieval_config_allows_no_rerank_comparisons() -> None:
    config = RetrievalConfigIn.model_validate({"mode": "vector", "top_k_rerank": 0})

    assert config.mode == "vector"
    assert config.top_k_rerank == 0


@pytest.mark.unit
def test_query_retrieval_config_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        RetrievalConfigIn.model_validate({"mode": "semantic-ish"})


@pytest.mark.unit
def test_access_filter_rejects_unknown_access_level() -> None:
    with pytest.raises(ValueError, match="Unknown access level"):
        AccessFilter(require_access_level="owner")


@pytest.mark.unit
def test_access_filter_builds_authorized_collection_predicate() -> None:
    requested = [uuid4(), uuid4()]
    predicate = AccessFilter().build(auth=_auth(), collection_ids=requested)

    assert "WITH authorized_collections AS" in (predicate.cte_sql or "")
    assert "collection_access_policies" in (predicate.cte_sql or "")
    assert "authorized_collections" in predicate.sql
    assert "requested_collection_ids" in predicate.sql
    assert predicate.params["auth_user_id"] == str(_auth().user_id)
    assert predicate.params["auth_tenant_id"] == str(_auth().tenant_id)
    assert predicate.params["min_access_rank"] == 1
    assert predicate.params["requested_collection_ids"] == [str(c) for c in requested]
    assert "CAST(:requested_collection_ids AS uuid[])" in predicate.sql


@pytest.mark.unit
def test_access_filter_tenant_visibility_only_grants_read() -> None:
    read_predicate = AccessFilter(require_access_level="read").build(
        auth=_auth(), collection_ids=None
    )
    write_predicate = AccessFilter(require_access_level="write").build(
        auth=_auth(), collection_ids=None
    )

    assert read_predicate.params["min_access_rank"] == 1
    assert write_predicate.params["min_access_rank"] == 2
    assert "(c.visibility = 'tenant' AND :min_access_rank <= 1)" in (
        write_predicate.cte_sql or ""
    )


@pytest.mark.unit
def test_access_filter_uses_configured_chunk_alias() -> None:
    predicate = AccessFilter(chunks_alias="dc").build(auth=_auth(), collection_ids=None)

    assert "dc.document_id" in predicate.sql
    assert "requested_collection_ids" not in predicate.params


@pytest.mark.unit
def test_rrf_merge_dedupes_and_combines_scores() -> None:
    shared_chunk_id = uuid4()
    bm25 = [_candidate(RetrievalStage.BM25, rank=2, chunk_id=shared_chunk_id)]
    vector = [_candidate(RetrievalStage.VECTOR, rank=3, chunk_id=shared_chunk_id)]

    merged = merge_with_rrf(bm25=bm25, vector=vector, top_k=10)

    expected_score = 1 / (60 + 2) + 1 / (60 + 3)
    assert len(merged) == 1
    assert merged[0].chunk_id == shared_chunk_id
    assert merged[0].score == pytest.approx(expected_score)
    assert merged[0].rank == 1
    assert merged[0].stage is RetrievalStage.HYBRID_MERGE
    assert merged[0].metadata == {"bm25_rank": 2, "vector_rank": 3}


@pytest.mark.unit
def test_rrf_merge_honors_top_k_and_vector_only_metadata() -> None:
    vector = [
        _candidate(RetrievalStage.VECTOR, rank=1),
        _candidate(RetrievalStage.VECTOR, rank=2),
    ]

    merged = merge_with_rrf(bm25=[], vector=vector, top_k=1)

    assert len(merged) == 1
    assert merged[0].metadata == {"bm25_rank": None, "vector_rank": 1}


@pytest.mark.unit
def test_rrf_merge_rejects_invalid_rank_and_rrf_k() -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        merge_with_rrf(bm25=[], vector=[], top_k=10, rrf_k=0)

    with pytest.raises(ValueError, match="Candidate rank"):
        merge_with_rrf(
            bm25=[_candidate(RetrievalStage.BM25, rank=0)],
            vector=[],
            top_k=10,
        )


@pytest.mark.unit
def test_format_vector_casts_values_to_pgvector_literal() -> None:
    assert _format_vector([1, 2.5, -0.25]) == "[1.0,2.5,-0.25]"


@pytest.mark.unit
def test_pgvector_search_rejects_unsupported_embedding_dimension() -> None:
    embedder = FakeEmbedder()
    embedder.dimension = 384

    with pytest.raises(VectorSearchError, match="Unsupported embedding dim"):
        PgvectorVectorSearch(session=FakeSqlSession(), embedder=embedder)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pgvector_search_sets_ef_search_and_uses_dimension_column() -> None:
    row = type(
        "Row",
        (),
        {
            "id": uuid4(),
            "document_id": uuid4(),
            "content": "vector search",
            "page_number": 4,
            "section_title": "Retrieval",
            "score": 0.91,
        },
    )()
    session = FakeSqlSession(rows=[row])
    search = PgvectorVectorSearch(
        session=session,  # type: ignore[arg-type]
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
    )

    out = await search.search(
        query="vector",
        auth=_auth(),
        collection_ids=[uuid4()],
        top_k=3,
        ef_search=77,
    )

    assert "SET LOCAL hnsw.ef_search = 77" in session.calls[0][0]
    sql, params = session.calls[1]
    assert "ce.embedding_768" in sql
    assert params["query_vec"] == "[0.1,0.2,0.3]"
    assert params["embedding_model"] == "ollama/nomic-embed-text"
    assert out[0].stage is RetrievalStage.VECTOR
    assert out[0].score == pytest.approx(0.91)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_keyword_search_and_opensearch_share_access_filter_shape() -> None:
    session = FakeSqlSession()
    search = PostgresFtsKeywordSearch(
        session=session,  # type: ignore[arg-type]
        access_filter=AccessFilter(),
    )
    requested = [uuid4()]

    await search.search(query="kubernetes", auth=_auth(), collection_ids=requested, top_k=5)

    sql, params = session.calls[0]
    assert "WITH authorized_collections AS" in sql
    assert "collection_access_policies" in sql
    assert "requested_collection_ids" in sql
    assert params["requested_collection_ids"] == [str(requested[0])]
