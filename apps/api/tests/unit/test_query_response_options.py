"""Unit coverage for query response option mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from app.api.v1.routes import query as query_routes
from app.api.v1.routes.query import _build_trace, _coerce_metadata, _to_query_response
from app.schemas.query import GenerationConfigIn, QueryRequest, RetrievalConfigIn
from app.services.rag import CitationOut, QueryOptions, QueryResult
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors import RBACDeniedError
from starlette.responses import StreamingResponse


class FakeResult:
    def __init__(self, *, one: object | None = None, many: list[object] | None = None) -> None:
        self.one = one
        self.many = many or []

    def fetchone(self) -> object | None:
        return self.one

    def fetchall(self) -> list[object]:
        return self.many


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.calls = 0

    async def execute(self, *_args: object, **_kwargs: object) -> FakeResult:
        result = self.results[self.calls]
        self.calls += 1
        return result


def _auth(*, permissions: frozenset[str] = frozenset({"queries:execute"})) -> AuthContext:
    return AuthContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        email="demo@example.com",
        permissions=permissions,
    )


def _result_with_citation() -> QueryResult:
    return QueryResult(
        query_session_id=uuid4(),
        answer="Rollback uses the Helm release history [1].",
        confidence_score=None,
        grounding_score=0.9,
        hallucination_risk_score=None,
        citations=[
            CitationOut(
                citation_id=uuid4(),
                chunk_id=uuid4(),
                document_id=uuid4(),
                citation_index=1,
                quoted_text="Helm stores release history for rollback.",
                page_number=3,
                section_title="Operations",
                relevance_score=0.82,
            )
        ],
        input_tokens=120,
        output_tokens=24,
        cost_usd=0.0012,
        latency_ms=345,
    )


def _request(*, model: str = "ollama/llama3.1:8b") -> QueryRequest:
    return QueryRequest(
        query="How do rollbacks work?",
        collection_ids=[uuid4()],
        retrieval=RetrievalConfigIn(top_k_rerank=0),
        generation=GenerationConfigIn(model=model),
    )


async def _collect_stream(response: StreamingResponse, *, limit: int = 10) -> list[bytes]:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
        if len(chunks) >= limit:
            break
    return chunks


@pytest.mark.unit
def test_query_response_includes_citations_by_default() -> None:
    response = _to_query_response(_result_with_citation())

    assert len(response.citations) == 1
    assert response.citations[0].citation_index == 1


@pytest.mark.unit
def test_query_response_can_hide_citations() -> None:
    response = _to_query_response(
        _result_with_citation(),
        include_citations=False,
    )

    assert response.citations == []
    assert response.usage.input_tokens == 120
    assert response.answer.startswith("Rollback uses")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"bm25_rank": 1}, {"bm25_rank": 1}),
        ('{"vector_rank": 2}', {"vector_rank": 2}),
        ("not-json", {}),
        ('["not", "an", "object"]', {}),
        (None, {}),
    ],
)
def test_trace_metadata_coercion(raw: object, expected: dict[str, object]) -> None:
    assert _coerce_metadata(raw) == expected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_trace_returns_none_for_missing_query_session() -> None:
    db = FakeSession([FakeResult(one=None)])

    trace = await _build_trace(db, uuid4())  # type: ignore[arg-type]

    assert trace is None
    assert db.calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_trace_maps_retrieval_and_generation_rows() -> None:
    query_session_id = uuid4()
    chunk_id = uuid4()
    prompt_version_id = uuid4()
    db = FakeSession(
        [
            FakeResult(
                one=SimpleNamespace(
                    id=query_session_id,
                    query_text="How do rollbacks work?",
                    status="completed",
                    latency_ms=123,
                    created_at=datetime(2026, 5, 12, tzinfo=UTC),
                )
            ),
            FakeResult(
                many=[
                    SimpleNamespace(
                        chunk_id=chunk_id,
                        retrieval_stage="rerank",
                        rank=1,
                        score=0.75,
                        metadata='{"reranker_model":"noop"}',
                    )
                ]
            ),
            FakeResult(
                one=SimpleNamespace(
                    model_name="ollama/llama3.1:8b",
                    prompt_version_id=prompt_version_id,
                    input_tokens=10,
                    output_tokens=5,
                    cost_usd=None,
                    grounding_score=0.8,
                    hallucination_risk_score=None,
                    confidence_score=None,
                )
            ),
        ]
    )

    trace = await _build_trace(db, query_session_id)  # type: ignore[arg-type]

    assert trace is not None
    assert trace.query_session_id == query_session_id
    assert trace.generation is not None
    assert trace.generation.cost_usd is None
    assert trace.generation.prompt_version_id == prompt_version_id
    assert trace.retrieval_results[0].chunk_id == chunk_id
    assert trace.retrieval_results[0].metadata == {"reranker_model": "noop"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_trace_allows_abstained_trace_without_generation() -> None:
    query_session_id = uuid4()
    db = FakeSession(
        [
            FakeResult(
                one=SimpleNamespace(
                    id=query_session_id,
                    query_text="Unknown question",
                    status="abstained",
                    latency_ms=50,
                    created_at=datetime(2026, 5, 12, tzinfo=UTC),
                )
            ),
            FakeResult(many=[]),
            FakeResult(one=None),
        ]
    )

    trace = await _build_trace(db, query_session_id)  # type: ignore[arg-type]

    assert trace is not None
    assert trace.status == "abstained"
    assert trace.retrieval_results == []
    assert trace.generation is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_trace_returns_sse_response_headers() -> None:
    response = await query_routes.stream_trace(
        uuid4(),
        _ctx=object(),  # type: ignore[arg-type]
        db=object(),  # type: ignore[arg-type]
    )

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_trace_waits_until_session_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_session_id = uuid4()
    calls = 0

    async def fake_build_trace(_db: object, _query_session_id: object) -> object | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return SimpleNamespace(
            status="completed",
            model_dump=lambda mode: {"query_session_id": str(query_session_id), "mode": mode},
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(query_routes, "_build_trace", fake_build_trace)
    monkeypatch.setattr(query_routes.asyncio, "sleep", no_sleep)

    response = await query_routes.stream_trace(
        query_session_id,
        _ctx=object(),  # type: ignore[arg-type]
        db=object(),  # type: ignore[arg-type]
    )

    chunks = await _collect_stream(response)

    assert chunks[0] == b": waiting-for-session\n\n"
    assert b"event: trace" in chunks[1]
    assert chunks[2] == b"event: done\ndata: {}\n\n"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_trace_times_out_when_never_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_build_trace(_db: object, _query_session_id: object) -> object:
        return SimpleNamespace(
            status="running",
            model_dump=lambda mode: {"status": "running", "mode": mode},
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(query_routes, "_SSE_MAX_TICKS", 2)
    monkeypatch.setattr(query_routes, "_build_trace", fake_build_trace)
    monkeypatch.setattr(query_routes.asyncio, "sleep", no_sleep)

    response = await query_routes.stream_trace(
        uuid4(),
        _ctx=object(),  # type: ignore[arg-type]
        db=object(),  # type: ignore[arg-type]
    )

    chunks = await _collect_stream(response)

    assert len([chunk for chunk in chunks if b"event: trace" in chunk]) == 2
    assert chunks[-1] == b'event: timeout\ndata: {"reason":"max-ticks-exceeded"}\n\n'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_query_rejects_cloud_model_without_permission() -> None:
    with pytest.raises(RBACDeniedError):
        await query_routes.execute_query(
            _request(model="openai/gpt-4o-mini"),
            ctx=_auth(),
            db=object(),  # type: ignore[arg-type]
            reranker=object(),  # type: ignore[arg-type]
            audit_storage=object(),  # type: ignore[arg-type]
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_query_passes_abstain_option_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeSettings:
        default_generation_model = "ollama/llama3.1:8b"
        default_embedding_model = "ollama/nomic-embed-text"
        ollama_base_url = "http://localhost:11434"

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def run(self, **kwargs: object) -> QueryResult:
            captured.update(kwargs)
            return QueryResult(
                query_session_id=uuid4(),
                answer="I do not have enough information in the provided sources.",
                confidence_score=None,
                grounding_score=0.0,
                hallucination_risk_score=None,
                citations=[],
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=12,
            )

    def fake_get_settings() -> FakeSettings:
        return FakeSettings()

    monkeypatch.setattr(query_routes, "get_settings", fake_get_settings)
    monkeypatch.setattr(query_routes, "Orchestrator", FakeOrchestrator)

    request = _request()
    request.options.abstain_if_unsupported = False
    request.options.include_citations = False

    response = await query_routes.execute_query(
        request,
        ctx=_auth(),
        db=object(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        audit_storage=object(),  # type: ignore[arg-type]
    )

    options = cast(QueryOptions, captured["options"])
    assert options.abstain_if_unsupported is False
    assert response.citations == []
    assert response.usage.cost_usd == 0.0
