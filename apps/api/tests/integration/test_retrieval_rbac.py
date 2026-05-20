"""RBAC pre-filter test — the headline of Phase 3.

Architectural pillar #1 (CLAUDE.md): RBAC is enforced AT retrieval time,
NOT post-mask. We prove this by:

    - Seeding two tenants A and B, each with a collection and a chunk.
    - Running the keyword search bound to tenant A's session.
    - Verifying ONLY tenant A's chunk is returned, even when we explicitly
      pass tenant B's collection_id (RLS + AccessFilter both deny it).

This test exercises the SQL path directly without spinning up the full
RagOrchestrator (which requires LLM access). The promise we test is
specifically the predicate at the SQL level.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.retrieval import (
    AccessFilter,
    PostgresFtsKeywordSearch,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_tenant_with_chunk(
    admin_session: AsyncSession,
    *,
    slug: str,
    chunk_text: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    """Returns (tenant_id, user_id, collection_id, chunk_id)."""
    from sqlalchemy import text  # noqa: PLC0415

    tenant_id = uuid4()
    user_id = uuid4()
    collection_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()

    await admin_session.execute(
        text("INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(tenant_id), "name": slug.title(), "slug": slug},
    )
    await admin_session.execute(
        text("INSERT INTO users (id, tenant_id, email) VALUES (:id, :tid, :email)"),
        {"id": str(user_id), "tid": str(tenant_id), "email": f"{slug}@test.local"},
    )
    # Tenant-visibility collections grant read by default — keeps the test
    # focused on the tenant-isolation path instead of access-policy joins.
    await admin_session.execute(
        text(
            "INSERT INTO collections (id, tenant_id, name, visibility) "
            "VALUES (:id, :tid, :name, 'tenant')"
        ),
        {"id": str(collection_id), "tid": str(tenant_id), "name": f"{slug}-collection"},
    )
    await admin_session.execute(
        text(
            "INSERT INTO documents "
            "(id, tenant_id, collection_id, title, source_type, checksum, status) "
            "VALUES (:id, :tid, :cid, :title, 'upload', :chk, 'indexed')"
        ),
        {
            "id": str(document_id),
            "tid": str(tenant_id),
            "cid": str(collection_id),
            "title": f"{slug} doc",
            "chk": f"sha-{slug}",
        },
    )
    await admin_session.execute(
        text(
            "INSERT INTO document_versions "
            "(id, tenant_id, document_id, version_number, content_hash, storage_uri) "
            "VALUES (:id, :tid, :did, 1, :h, :uri)"
        ),
        {
            "id": str(version_id),
            "tid": str(tenant_id),
            "did": str(document_id),
            "h": f"hash-{slug}",
            "uri": f"s3://test/{slug}/v1",
        },
    )
    await admin_session.execute(
        text(
            "INSERT INTO document_chunks "
            "(id, tenant_id, document_id, document_version_id, chunk_index, "
            " content) "
            "VALUES (:id, :tid, :did, :vid, 0, :content)"
        ),
        {
            "id": str(chunk_id),
            "tid": str(tenant_id),
            "did": str(document_id),
            "vid": str(version_id),
            "content": chunk_text,
        },
    )
    await admin_session.commit()
    return tenant_id, user_id, collection_id, chunk_id


@pytest.mark.integration
@pytest.mark.asyncio
class TestRBACAtRetrievalTime:
    async def test_keyword_search_excludes_other_tenants_chunks(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        # Both tenants have chunks containing the same word so the search query
        # would match BOTH if RBAC weren't enforced.
        a_tid, a_uid, a_cid, a_chunk = await _seed_tenant_with_chunk(
            admin_session,
            slug="acme",
            chunk_text="rolling deployments are the safe option for kubernetes",
        )
        _, _, b_cid, b_chunk = await _seed_tenant_with_chunk(
            admin_session,
            slug="beacon",
            chunk_text="rolling deployments require careful kubernetes config",
        )

        auth_a = AuthContext(
            user_id=a_uid,
            tenant_id=a_tid,
            email="acme@test.local",
            permissions=frozenset({"queries:execute", "collections:read"}),
        )

        # Run search bound to tenant A's session.
        get_a_session = tenant_session_factory(a_tid)
        async for sess in get_a_session():
            search = PostgresFtsKeywordSearch(session=sess, access_filter=AccessFilter())

            # Even when A explicitly requests both A's and B's collection,
            # only A's chunk should come back.
            results = await search.search(
                query="rolling deployments kubernetes",
                auth=auth_a,
                collection_ids=[a_cid, b_cid],
                top_k=10,
            )

        chunk_ids_returned = {r.chunk_id for r in results}
        assert a_chunk in chunk_ids_returned, "A's chunk MUST be in results"
        assert b_chunk not in chunk_ids_returned, (
            "B's chunk leaked into A's retrieval — RBAC is post-mask, not pre-filter"
        )

    async def test_keyword_search_filters_to_requested_collection(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        cleanup_db,
    ) -> None:
        # Same tenant, two collections. Verify collection_ids scope works.
        a_tid, a_uid, a_cid, a_chunk = await _seed_tenant_with_chunk(
            admin_session,
            slug="acme",
            chunk_text="alpha content keyword",
        )

        # Add a second collection + chunk in the SAME tenant.
        from sqlalchemy import text  # noqa: PLC0415

        other_cid = uuid4()
        other_doc = uuid4()
        other_ver = uuid4()
        other_chunk = uuid4()
        await admin_session.execute(
            text(
                "INSERT INTO collections (id, tenant_id, name, visibility) "
                "VALUES (:id, :tid, 'acme-other', 'tenant')"
            ),
            {"id": str(other_cid), "tid": str(a_tid)},
        )
        await admin_session.execute(
            text(
                "INSERT INTO documents "
                "(id, tenant_id, collection_id, title, source_type, checksum) "
                "VALUES (:id, :tid, :cid, 'other', 'upload', 'sha-other')"
            ),
            {"id": str(other_doc), "tid": str(a_tid), "cid": str(other_cid)},
        )
        await admin_session.execute(
            text(
                "INSERT INTO document_versions "
                "(id, tenant_id, document_id, version_number, content_hash, storage_uri) "
                "VALUES (:id, :tid, :did, 1, 'h', 'uri')"
            ),
            {"id": str(other_ver), "tid": str(a_tid), "did": str(other_doc)},
        )
        await admin_session.execute(
            text(
                "INSERT INTO document_chunks "
                "(id, tenant_id, document_id, document_version_id, chunk_index, content) "
                "VALUES (:id, :tid, :did, :vid, 0, 'alpha content keyword in other collection')"
            ),
            {
                "id": str(other_chunk),
                "tid": str(a_tid),
                "did": str(other_doc),
                "vid": str(other_ver),
            },
        )
        await admin_session.commit()

        auth = AuthContext(
            user_id=a_uid,
            tenant_id=a_tid,
            email="acme@test.local",
            permissions=frozenset({"queries:execute"}),
        )
        get_session = tenant_session_factory(a_tid)
        async for sess in get_session():
            search = PostgresFtsKeywordSearch(session=sess, access_filter=AccessFilter())
            # Request ONLY the first collection; the other-collection chunk must
            # not appear.
            results = await search.search(
                query="alpha content keyword",
                auth=auth,
                collection_ids=[a_cid],
                top_k=10,
            )

        chunk_ids = {r.chunk_id for r in results}
        assert a_chunk in chunk_ids
        assert other_chunk not in chunk_ids, (
            "collection_ids scope was not honored at retrieval time"
        )
