"""Tests for the standalone retrieval-service FastAPI app."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sentinelrag_retrieval_service.main import app


@pytest.mark.unit
def test_health_and_capabilities() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "sentinelrag-retrieval-service"

    capabilities = client.get("/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["modes"] == ["hybrid", "bm25", "vector"]
    assert body["rbac_at_retrieval_time"] is True


@pytest.mark.unit
def test_rrf_merge_deduplicates_and_ranks() -> None:
    client = TestClient(app)
    shared_chunk_id = uuid4()
    document_id = uuid4()

    response = client.post(
        "/rrf-merge",
        json={
            "bm25": [
                {
                    "chunk_id": str(shared_chunk_id),
                    "document_id": str(document_id),
                    "content": "postgres hnsw retrieval",
                    "score": 9.0,
                    "rank": 1,
                }
            ],
            "vector": [
                {
                    "chunk_id": str(shared_chunk_id),
                    "document_id": str(document_id),
                    "content": "postgres hnsw retrieval",
                    "score": 0.9,
                    "rank": 1,
                }
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
