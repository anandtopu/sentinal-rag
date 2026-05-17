"""Unit coverage for HttpRetrievalClient (R4.S2).

Uses httpx's MockTransport to exercise the wire shape, retry, and error
paths without spinning up the retrieval-service. The mock transport
lets us assert exactly what the client sends and respond with any
canned status code.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from app.services.rag.client import HttpRetrievalClient, RetrievalClientError
from sentinelrag_shared.auth import AuthContext


def _auth() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="demo@example.com",
        permissions=frozenset({"queries:execute"}),
    )


def _build_client(handler: httpx.MockTransport, **kwargs: object) -> HttpRetrievalClient:
    return HttpRetrievalClient(
        base_url="http://retrieval.test",
        service_token="t0p-s3cret",
        client=httpx.AsyncClient(
            base_url="http://retrieval.test", transport=handler
        ),
        max_retries=kwargs.get("max_retries", 3),  # type: ignore[arg-type]
        timeout_seconds=kwargs.get("timeout_seconds", 5.0),  # type: ignore[arg-type]
    )


def _ok_response(*, embedding_usage: bool = True) -> dict[str, object]:
    chunk_id = uuid4()
    document_id = uuid4()
    candidate = {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "content": "rollback procedure documented",
        "score": 0.83,
        "rank": 1,
        "stage": "hybrid_merge",
        "page_number": 12,
        "section_title": "Operations",
        "metadata": {"bm25_rank": 2, "vector_rank": 1},
    }
    body: dict[str, object] = {
        "bm25_candidates": [],
        "vector_candidates": [],
        "merged_candidates": [candidate],
        "metadata": {"mode": "hybrid"},
        "embedding_usage": (
            {
                "provider": "ollama",
                "model_name": "ollama/nomic-embed-text",
                "input_tokens": 7,
                "output_tokens": 0,
                "total_cost_usd": "0",
                "latency_ms": 42,
            }
            if embedding_usage
            else None
        ),
    }
    return body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_sends_bearer_token_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        captured["path"] = request.url.path
        return httpx.Response(200, json=_ok_response())

    client = _build_client(httpx.MockTransport(handler))
    try:
        result = await client.retrieve(
            query="rollback",
            auth=_auth(),
            collection_ids=[],
            mode="hybrid",
            top_k_bm25=10,
            top_k_vector=10,
            top_k_hybrid=20,
            ef_search=None,
        )
    finally:
        await client.aclose()

    assert captured["path"] == "/v1/retrieve"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer t0p-s3cret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["query"] == "rollback"
    assert body["mode"] == "hybrid"
    assert "auth" in body
    assert len(result.merged_candidates) == 1
    candidate = result.merged_candidates[0]
    assert candidate.content == "rollback procedure documented"
    assert candidate.stage.value == "hybrid_merge"
    assert result.embedding_usage is not None
    assert result.embedding_usage.input_tokens == 7
    assert result.embedding_usage.total_cost_usd == Decimal("0")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_retries_on_503_then_succeeds() -> None:
    """A transient 503 should be retried; subsequent 200 returns cleanly."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"detail": "warming up"})
        return httpx.Response(200, json=_ok_response())

    client = _build_client(httpx.MockTransport(handler), max_retries=3)
    try:
        result = await client.retrieve(
            query="rollback",
            auth=_auth(),
            collection_ids=[],
            mode="hybrid",
            top_k_bm25=10,
            top_k_vector=10,
            top_k_hybrid=20,
            ef_search=None,
        )
    finally:
        await client.aclose()
    assert calls["n"] == 2
    assert len(result.merged_candidates) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_does_not_retry_on_4xx() -> None:
    """A 401/422 from the service is a caller bug — fail fast, no retry."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(401, json={"detail": "bad token"})

    client = _build_client(httpx.MockTransport(handler), max_retries=3)
    try:
        with pytest.raises(RetrievalClientError, match="401"):
            await client.retrieve(
                query="rollback",
                auth=_auth(),
                collection_ids=[],
                mode="hybrid",
                top_k_bm25=10,
                top_k_vector=10,
                top_k_hybrid=20,
                ef_search=None,
            )
    finally:
        await client.aclose()
    assert calls["n"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_exhausts_retries_on_persistent_503() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(503, json={"detail": "still warming up"})

    client = _build_client(httpx.MockTransport(handler), max_retries=2)
    try:
        with pytest.raises(RetrievalClientError):
            await client.retrieve(
                query="rollback",
                auth=_auth(),
                collection_ids=[],
                mode="hybrid",
                top_k_bm25=10,
                top_k_vector=10,
                top_k_hybrid=20,
                ef_search=None,
            )
    finally:
        await client.aclose()
    assert calls["n"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_bm25_mode_does_not_attach_embedding_usage() -> None:
    """bm25-only never embeds — service returns None, client preserves it."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["mode"] == "bm25"
        return httpx.Response(200, json=_ok_response(embedding_usage=False))

    client = _build_client(httpx.MockTransport(handler))
    try:
        result = await client.retrieve(
            query="rollback",
            auth=_auth(),
            collection_ids=[],
            mode="bm25",
            top_k_bm25=10,
            top_k_vector=10,
            top_k_hybrid=20,
            ef_search=None,
        )
    finally:
        await client.aclose()
    assert result.embedding_usage is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_rejects_unsupported_mode() -> None:
    """Mode validation runs before the network call."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_ok_response())

    client = _build_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(RetrievalClientError, match="unsupported mode"):
            await client.retrieve(
                query="rollback",
                auth=_auth(),
                collection_ids=[],
                mode="bogus",
                top_k_bm25=10,
                top_k_vector=10,
                top_k_hybrid=20,
                ef_search=None,
            )
    finally:
        await client.aclose()
