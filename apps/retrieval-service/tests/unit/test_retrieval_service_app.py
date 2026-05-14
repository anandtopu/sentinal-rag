"""Tests for the standalone retrieval-service FastAPI app."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sentinelrag_retrieval_service.main import app


def _candidate_json(
    *,
    chunk_id: str | None = None,
    document_id: str | None = None,
    content: str = "postgres hnsw retrieval",
    score: float = 1.0,
    rank: int = 1,
    page_number: int | None = None,
    section_title: str | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id or str(uuid4()),
        "document_id": document_id or str(uuid4()),
        "content": content,
        "score": score,
        "rank": rank,
        "page_number": page_number,
        "section_title": section_title,
        "metadata": metadata or {},
    }


@pytest.mark.unit
def test_health_and_capabilities() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "sentinelrag-retrieval-service"

    capabilities = client.get("/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["service_role"] == "diagnostic-wrapper"
    assert body["modes"] == ["rrf_merge"]
    assert body["endpoints"] == ["/rrf-merge"]
    assert body["retrieval_backends"] == []
    assert body["rbac_at_retrieval_time"] is False


@pytest.mark.unit
def test_rrf_merge_deduplicates_and_ranks() -> None:
    client = TestClient(app)
    shared_chunk_id = uuid4()
    document_id = uuid4()

    response = client.post(
        "/rrf-merge",
        json={
            "bm25": [
                _candidate_json(
                    chunk_id=str(shared_chunk_id),
                    document_id=str(document_id),
                    score=9.0,
                    rank=1,
                )
            ],
            "vector": [
                _candidate_json(
                    chunk_id=str(shared_chunk_id),
                    document_id=str(document_id),
                    score=0.9,
                    rank=1,
                )
            ],
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["chunk_id"] == str(shared_chunk_id)
    assert candidates[0]["stage"] == "hybrid_merge"
    assert candidates[0]["metadata"] == {"bm25_rank": 1, "vector_rank": 1}


@pytest.mark.unit
def test_rrf_merge_vector_only_preserves_candidate_fields() -> None:
    client = TestClient(app)
    payload = _candidate_json(
        content="semantic vector hit",
        score=0.82,
        rank=3,
        page_number=12,
        section_title="Architecture",
        metadata={"source": "vector"},
    )

    response = client.post(
        "/rrf-merge",
        json={"bm25": [], "vector": [payload], "top_k": 10, "rrf_k": 60},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["content"] == "semantic vector hit"
    assert candidate["rank"] == 1
    assert candidate["stage"] == "hybrid_merge"
    assert candidate["page_number"] == 12
    assert candidate["section_title"] == "Architecture"
    assert candidate["metadata"] == {"bm25_rank": None, "vector_rank": 3}


@pytest.mark.unit
def test_rrf_merge_honors_top_k_and_zero_top_k() -> None:
    client = TestClient(app)
    response = client.post(
        "/rrf-merge",
        json={
            "bm25": [
                _candidate_json(content="first", rank=1),
                _candidate_json(content="second", rank=2),
            ],
            "vector": [],
            "top_k": 1,
        },
    )
    assert response.status_code == 200
    assert [c["content"] for c in response.json()["candidates"]] == ["first"]

    empty = client.post(
        "/rrf-merge",
        json={"bm25": [_candidate_json()], "vector": [], "top_k": 0},
    )
    assert empty.status_code == 200
    assert empty.json()["candidates"] == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (
            {"bm25": [_candidate_json(rank=0)], "vector": []},
            "rank",
        ),
        (
            {"bm25": [], "vector": [], "top_k": 201},
            "top_k",
        ),
        (
            {"bm25": [], "vector": [], "rrf_k": 0},
            "rrf_k",
        ),
        (
            {"bm25": [_candidate_json(chunk_id="not-a-uuid")], "vector": []},
            "chunk_id",
        ),
    ],
)
def test_rrf_merge_rejects_invalid_payloads(
    payload: dict[str, object],
    field: str,
) -> None:
    client = TestClient(app)

    response = client.post("/rrf-merge", json=payload)

    assert response.status_code == 422
    error_locations = {error["loc"][-1] for error in response.json()["detail"]}
    assert field in error_locations
