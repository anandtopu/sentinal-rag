"""OpenSearch implementation of the KeywordSearch protocol (ADR-0026).

Plugs in behind the same ``KeywordSearch`` protocol as
:class:`PostgresFtsKeywordSearch` (ADR-0004). Phase 8 reintroduces
OpenSearch as a parallel adapter so the two can be A/B'd against each
other without changing call sites.

RBAC strategy
-------------
OpenSearch lives outside the Postgres RLS perimeter. Tenant isolation +
collection authorization can't ride on RLS, so we apply them as
*query-time filters*:

    1. Resolve the authorized collection set for the user via a single
       Postgres query (re-uses the same ``authorized_collections`` CTE
       that :class:`AccessFilter` already builds).
    2. Issue an OpenSearch query whose ``filter`` clause `terms`-matches
       on ``collection_id`` AND ``tenant_id``.

Postgres remains the source of truth for RBAC. OpenSearch only gets a
constant-time list-membership check — fast and easy to audit.

Indexing
--------
Documents are denormalized so the search index never needs a join. Each
indexed doc carries ``tenant_id``, ``collection_id``, ``document_id``,
``chunk_id``, ``content``, ``page_number``, ``section_title``. The
ingestion pipeline calls :meth:`bulk_index` after a Temporal activity
finalizes a document version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.retrieval.access_filter import AccessFilter
from sentinelrag_shared.retrieval.candidate import Candidate, RetrievalStage

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch


DEFAULT_INDEX_NAME = "sentinelrag-chunks"


@dataclass(slots=True)
class IndexableChunk:
    """The denormalized shape we ship to OpenSearch.

    Built from a ``document_chunks`` row joined with its ``documents``
    row at ingestion time so the search engine never needs to call back
    to Postgres at query time.
    """

    chunk_id: UUID
    document_id: UUID
    tenant_id: UUID
    collection_id: UUID
    content: str
    page_number: int | None = None
    section_title: str | None = None


# Index template — applied once at bootstrap. Keep mappings strict so a
# typo in a producer can't silently change the index shape.
INDEX_MAPPINGS: dict[str, Any] = {
    "settings": {
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard",
                }
            }
        },
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "chunk_id":       {"type": "keyword"},
            "document_id":    {"type": "keyword"},
            "tenant_id":      {"type": "keyword"},
            "collection_id":  {"type": "keyword"},
            "content":        {"type": "text",    "analyzer": "standard"},
            "page_number":    {"type": "integer"},
            "section_title":  {"type": "keyword"},
        },
    },
}


class OpenSearchKeywordSearch:
    """OpenSearch BM25-backed keyword search.

    Args:
        client: An ``AsyncOpenSearch`` client (opensearch-py). Caller owns
            the lifecycle.
        session: AsyncSession used to resolve the authorized-collection
            set at query time. The session must already be bound to the
            tenant context (RLS-enabled) so the CTE only sees the
            caller's tenant.
        index_name: OpenSearch index alias. Default ``sentinelrag-chunks``.
        access_filter: Reused for the authorized-collections CTE; we do
            NOT use its predicate output (that's Postgres-flavored SQL),
            only the CTE shape.
    """

    def __init__(
        self,
        *,
        client: AsyncOpenSearch,
        session: AsyncSession,
        index_name: str = DEFAULT_INDEX_NAME,
        access_filter: AccessFilter | None = None,
    ) -> None:
        self.client = client
        self.session = session
        self.index_name = index_name
        self.access_filter = access_filter or AccessFilter()

    async def search(
        self,
        *,
        query: str,
        auth: AuthContext,
        collection_ids: list[UUID] | None,
        top_k: int,
    ) -> list[Candidate]:
        if not query.strip() or top_k <= 0:
            return []

        authorized_ids = await self._resolve_authorized_collections(
            auth=auth,
            requested=collection_ids,
        )
        if not authorized_ids:
            return []

        body = {
            "size": top_k,
            "_source": [
                "chunk_id",
                "document_id",
                "content",
                "page_number",
                "section_title",
            ],
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "content": {
                                    "query": query,
                                    "operator": "or",
                                }
                            }
                        }
                    ],
                    "filter": [
                        {"term":  {"tenant_id": str(auth.tenant_id)}},
                        {"terms": {"collection_id": [str(cid) for cid in authorized_ids]}},
                    ],
                }
            },
        }

        response = await self.client.search(index=self.index_name, body=body)
        hits = response.get("hits", {}).get("hits", [])

        return [
            Candidate(
                chunk_id=UUID(src["chunk_id"]),
                document_id=UUID(src["document_id"]),
                content=src["content"],
                score=float(hit.get("_score") or 0.0),
                rank=rank,
                stage=RetrievalStage.BM25,
                page_number=src.get("page_number"),
                section_title=src.get("section_title"),
            )
            for rank, hit in enumerate(hits, start=1)
            for src in [hit["_source"]]
        ]

    async def _resolve_authorized_collections(
        self,
        *,
        auth: AuthContext,
        requested: list[UUID] | None,
    ) -> list[UUID]:
        """Single Postgres call to compute the authorized collection set.

        Reuses the same authorized_collections CTE that
        :class:`AccessFilter` builds. We don't apply the chunk-level
        EXISTS predicate here — we only want the set of collection IDs.
        """
        predicate = self.access_filter.build(auth=auth, collection_ids=requested)
        # CTE plus a trivial SELECT against it. predicate.params already
        # carries auth_user_id, auth_tenant_id, min_access_rank.
        sql = (predicate.cte_sql or "") + "\nSELECT collection_id FROM authorized_collections"

        result = await self.session.execute(text(sql), predicate.params)
        ids = [UUID(str(row.collection_id)) for row in result.fetchall()]

        if requested:
            requested_set = {str(c) for c in requested}
            ids = [c for c in ids if str(c) in requested_set]
        return ids

    async def bulk_index(
        self,
        chunks: list[IndexableChunk],
        *,
        refresh: bool = False,
    ) -> int:
        """Bulk-index chunks. Returns the count successfully indexed.

        ``refresh=True`` forces an immediate refresh; expensive at scale
        — only used by integration tests that need read-after-write.
        """
        if not chunks:
            return 0

        lines: list[str] = []
        for chunk in chunks:
            header = {"index": {"_index": self.index_name, "_id": str(chunk.chunk_id)}}
            lines.append(json.dumps(header))
            lines.append(json.dumps({
                "chunk_id":      str(chunk.chunk_id),
                "document_id":   str(chunk.document_id),
                "tenant_id":     str(chunk.tenant_id),
                "collection_id": str(chunk.collection_id),
                "content":       chunk.content,
                "page_number":   chunk.page_number,
                "section_title": chunk.section_title,
            }))
        body = "\n".join(lines) + "\n"

        response = await self.client.bulk(
            body=body,
            params={"refresh": str(refresh).lower()},
        )
        if response.get("errors"):
            failed = sum(
                1
                for item in response.get("items", [])
                if next(iter(item.values())).get("error")
            )
            return len(chunks) - failed
        return len(chunks)

    async def delete_by_document(self, *, tenant_id: UUID, document_id: UUID) -> int:
        """Delete all chunks of a document. Returns deleted count.

        Used by the ingestion pipeline when a document version is
        superseded — the old chunks are evicted from the search index.
        """
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"tenant_id":   str(tenant_id)}},
                        {"term": {"document_id": str(document_id)}},
                    ]
                }
            }
        }
        response = await self.client.delete_by_query(
            index=self.index_name,
            body=body,
            params={"refresh": "true"},
        )
        return int(response.get("deleted", 0))

    async def ensure_index(self) -> bool:
        """Create the index with the canonical mappings if it doesn't exist.

        Returns True if a fresh index was created, False if one already
        existed. Idempotent; safe to call from a worker bootstrap activity.
        """
        exists = await self.client.indices.exists(index=self.index_name)
        if exists:
            return False
        await self.client.indices.create(index=self.index_name, body=INDEX_MAPPINGS)
        return True
