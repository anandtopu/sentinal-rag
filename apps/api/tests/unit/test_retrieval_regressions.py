"""Regression tests for retrieval configuration and shared retriever behavior."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from app.schemas.query import RetrievalConfigIn
from pydantic import ValidationError
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.retrieval import Candidate, HybridRetriever, RetrievalStage


def _auth() -> AuthContext:
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        email="demo@example.com",
        permissions=frozenset({"queries:execute"}),
    )


def _candidate(stage: RetrievalStage, rank: int = 1) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
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
