"""Unit tests for the OpenSearch KeywordSearch adapter (ADR-0026).

These tests stub OpenSearch and Postgres so they run without either
process. Integration coverage (against a real opensearch container) lives
under ``tests/integration``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.retrieval.candidate import RetrievalStage
from sentinelrag_shared.retrieval.opensearch_keyword_search import (
    DEFAULT_INDEX_NAME,
    INDEX_MAPPINGS,
    IndexableChunk,
    OpenSearchKeywordSearch,
)


def _auth() -> AuthContext:
    return AuthContext(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        email="demo@example.com",
        permissions=frozenset({"query:execute"}),
    )


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class FakeRow:
    def __init__(self, collection_id: UUID) -> None:
        self.collection_id = collection_id


class FakeSession:
    """Minimal AsyncSession stand-in.

    Captures the SQL + params each ``execute`` call receives so we can
    assert the adapter routed the right query through.
    """

    def __init__(self, return_collection_ids: list[UUID] | None = None) -> None:
        self._returns = return_collection_ids or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement, params: dict[str, Any] | None = None) -> FakeResult:
        # ``statement`` is a TextClause; rendering with str() gives the SQL.
        self.calls.append((str(statement), dict(params or {})))
        return FakeResult([FakeRow(cid) for cid in self._returns])


def _make_client(*, search_response: dict[str, Any] | None = None) -> AsyncMock:
    client = AsyncMock()
    client.search = AsyncMock(return_value=search_response or {"hits": {"hits": []}})
    client.bulk = AsyncMock(return_value={"errors": False, "items": []})
    client.delete_by_query = AsyncMock(return_value={"deleted": 0})
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock(return_value={"acknowledged": True})
    return client


# --------------------------------------------------------------------------- #
#                                   search                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearch:
    async def test_empty_query_short_circuits(self) -> None:
        adapter = OpenSearchKeywordSearch(
            client=_make_client(),
            session=FakeSession(),
        )
        out = await adapter.search(query="   ", auth=_auth(), collection_ids=None, top_k=5)
        assert out == []

    async def test_zero_top_k_short_circuits(self) -> None:
        adapter = OpenSearchKeywordSearch(
            client=_make_client(),
            session=FakeSession(),
        )
        out = await adapter.search(query="kubernetes", auth=_auth(), collection_ids=None, top_k=0)
        assert out == []

    async def test_no_authorized_collections_returns_empty(self) -> None:
        # Postgres returns no collections -> we must NOT call OpenSearch.
        client = _make_client()
        adapter = OpenSearchKeywordSearch(
            client=client,
            session=FakeSession(return_collection_ids=[]),
        )
        out = await adapter.search(query="kubernetes", auth=_auth(), collection_ids=None, top_k=10)
        assert out == []
        client.search.assert_not_called()

    async def test_filters_by_tenant_and_authorized_collections(self) -> None:
        cid_a, cid_b = uuid4(), uuid4()
        chunk_id, doc_id = uuid4(), uuid4()

        client = _make_client(
            search_response={
                "hits": {
                    "hits": [
                        {
                            "_score": 4.2,
                            "_source": {
                                "chunk_id":      str(chunk_id),
                                "document_id":   str(doc_id),
                                "content":       "kubernetes rolling update guide",
                                "page_number":   3,
                                "section_title": "Rollouts",
                            },
                        }
                    ]
                }
            }
        )
        adapter = OpenSearchKeywordSearch(
            client=client,
            session=FakeSession(return_collection_ids=[cid_a, cid_b]),
        )

        out = await adapter.search(query="kubernetes", auth=_auth(), collection_ids=None, top_k=5)

        assert len(out) == 1
        assert out[0].chunk_id == chunk_id
        assert out[0].document_id == doc_id
        assert out[0].score == pytest.approx(4.2)
        assert out[0].rank == 1
        assert out[0].stage is RetrievalStage.BM25
        assert out[0].page_number == 3
        assert out[0].section_title == "Rollouts"

        # Inspect the body: tenant filter + collection filter set correctly.
        client.search.assert_awaited_once()
        kwargs = client.search.await_args.kwargs
        body = kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"tenant_id": str(_auth().tenant_id)}} in filters
        terms = next(f for f in filters if "terms" in f)
        assert sorted(terms["terms"]["collection_id"]) == sorted([str(cid_a), str(cid_b)])
        assert body["size"] == 5

    async def test_caller_supplied_collection_intersects_authorized(self) -> None:
        # Caller asks for [A, X] but is only authorized on [A, B] —
        # the search must filter to just [A].
        cid_a, cid_b, cid_x = uuid4(), uuid4(), uuid4()
        client = _make_client()
        session = FakeSession(return_collection_ids=[cid_a, cid_b])

        adapter = OpenSearchKeywordSearch(client=client, session=session)
        await adapter.search(
            query="kubernetes",
            auth=_auth(),
            collection_ids=[cid_a, cid_x],
            top_k=5,
        )

        # Postgres CTE was passed the requested set so the
        # AccessFilter.params include requested_collection_ids.
        _sql, params = session.calls[-1]
        assert params["requested_collection_ids"] == [str(cid_a), str(cid_x)]

        # OpenSearch query terms-match only the intersection.
        terms = next(
            f for f in client.search.await_args.kwargs["body"]["query"]["bool"]["filter"]
            if "terms" in f
        )
        assert terms["terms"]["collection_id"] == [str(cid_a)]


# --------------------------------------------------------------------------- #
#                                bulk_index                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
class TestBulkIndex:
    async def test_no_chunks_no_call(self) -> None:
        client = _make_client()
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())

        n = await adapter.bulk_index([])
        assert n == 0
        client.bulk.assert_not_called()

    async def test_indexes_each_chunk(self) -> None:
        client = _make_client()
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())

        chunks = [
            IndexableChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                tenant_id=uuid4(),
                collection_id=uuid4(),
                content="hello world",
            ),
            IndexableChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                tenant_id=uuid4(),
                collection_id=uuid4(),
                content="another chunk",
                page_number=2,
                section_title="Intro",
            ),
        ]
        n = await adapter.bulk_index(chunks)
        assert n == 2

        body = client.bulk.await_args.kwargs["body"]
        # Two index ops + two source docs = 4 NDJSON lines (joined by \n
        # with a trailing \n, that's 4 newline characters total).
        assert body.count("\n") == 4
        # Index header points at the configured index name + the chunk_id
        # as the document id, so updates are idempotent.
        first_line = body.splitlines()[0]
        assert '"_index": "sentinelrag-chunks"' in first_line
        assert f'"_id": "{chunks[0].chunk_id}"' in first_line

    async def test_partial_failure_subtracts_failed(self) -> None:
        client = _make_client()
        client.bulk = AsyncMock(
            return_value={
                "errors": True,
                "items": [
                    {"index": {"status": 201}},
                    {"index": {"error": "mapper_parsing_exception"}},
                ],
            }
        )
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())
        chunks = [
            IndexableChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                tenant_id=uuid4(),
                collection_id=uuid4(),
                content="a",
            ),
            IndexableChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                tenant_id=uuid4(),
                collection_id=uuid4(),
                content="b",
            ),
        ]
        n = await adapter.bulk_index(chunks)
        assert n == 1


# --------------------------------------------------------------------------- #
#                              ensure_index                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
class TestEnsureIndex:
    async def test_creates_when_missing(self) -> None:
        client = _make_client()
        client.indices.exists = AsyncMock(return_value=False)
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())

        created = await adapter.ensure_index()
        assert created is True
        client.indices.create.assert_awaited_once()
        # The mappings we ship are the canonical ones.
        kwargs = client.indices.create.await_args.kwargs
        assert kwargs["index"] == DEFAULT_INDEX_NAME
        assert kwargs["body"] == INDEX_MAPPINGS

    async def test_skips_when_present(self) -> None:
        client = _make_client()
        client.indices.exists = AsyncMock(return_value=True)
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())

        created = await adapter.ensure_index()
        assert created is False
        client.indices.create.assert_not_called()


# --------------------------------------------------------------------------- #
#                              delete_by_document                             #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeleteByDocument:
    async def test_calls_delete_by_query_with_tenant_and_doc_filter(self) -> None:
        client = _make_client()
        client.delete_by_query = AsyncMock(return_value={"deleted": 7})
        adapter = OpenSearchKeywordSearch(client=client, session=FakeSession())

        tenant_id, doc_id = uuid4(), uuid4()
        n = await adapter.delete_by_document(tenant_id=tenant_id, document_id=doc_id)
        assert n == 7

        body = client.delete_by_query.await_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"tenant_id":   str(tenant_id)}} in filters
        assert {"term": {"document_id": str(doc_id)}} in filters
