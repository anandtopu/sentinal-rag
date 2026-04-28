"""End-to-end test for the document upload flow.

We exercise ``DocumentService.upload`` directly against:
    - real Postgres (testcontainers) with all migrations applied
    - real MinIO (testcontainers) for object storage
    - mocked Temporal client (the workflow itself has separate tests in the
      worker package; here we verify only that start_workflow was called with
      the right typed payload)
"""

from __future__ import annotations

import pytest
from app.db.models import Collection, Tenant, User
from app.schemas.documents import DocumentCreate
from app.services.document_service import DocumentService
from sentinelrag_shared.contracts import IngestionWorkflowInput
from sentinelrag_shared.object_storage import build_object_storage
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
class TestDocumentUpload:
    async def _seed_tenant_with_collection(
        self, admin_session: AsyncSession
    ) -> tuple[Tenant, User, Collection]:
        tenant = Tenant(name="Acme", slug="acme-upload", plan="enterprise")
        admin_session.add(tenant)
        await admin_session.flush()

        user = User(tenant_id=tenant.id, email="alice@acme.test", full_name="Alice")
        admin_session.add(user)
        await admin_session.flush()

        collection = Collection(
            tenant_id=tenant.id,
            name="upload-test",
            description="Upload integration test",
            visibility="tenant",
            created_by=user.id,
        )
        admin_session.add(collection)
        await admin_session.commit()
        for obj in (tenant, user, collection):
            await admin_session.refresh(obj)
        return tenant, user, collection

    async def test_upload_writes_to_storage_and_starts_workflow(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        minio_with_bucket: str,
        mock_temporal_client,
        cleanup_db,
    ) -> None:
        tenant, user, collection = await self._seed_tenant_with_collection(admin_session)

        get_session = tenant_session_factory(tenant.id)
        body = b"# Test document\n\nThis is some test content for ingestion."

        async for sess in get_session():
            storage = build_object_storage(
                provider="minio",
                bucket="sentinelrag-documents",
                region="us-east-1",
                endpoint=minio_with_bucket,
                access_key="minioadmin",
                secret_key="minioadmin",
                verify_ssl=False,
            )
            try:
                service = DocumentService(
                    sess,
                    storage=storage,
                    temporal_client=mock_temporal_client,
                    ingestion_task_queue="ingestion",
                    default_embedding_model="ollama/nomic-embed-text",
                )
                document, job = await service.upload(
                    tenant_id=tenant.id,
                    created_by=user.id,
                    payload=DocumentCreate(
                        collection_id=collection.id,
                        title="Test Doc",
                        sensitivity_level="internal",
                        metadata={"source": "test"},
                    ),
                    filename="test.md",
                    mime_type="text/markdown",
                    body=body,
                )
            finally:
                await storage.close()

        # 1. Document row created with correct attributes.
        assert document.tenant_id == tenant.id
        assert document.collection_id == collection.id
        assert document.title == "Test Doc"
        assert document.checksum  # SHA-256 set
        assert document.source_type == "upload"
        assert document.status == "pending"

        # 2. IngestionJob row created and tied to a workflow.
        assert job.tenant_id == tenant.id
        assert job.status == "queued"
        assert job.workflow_id is not None
        assert job.workflow_id == f"ingest-{job.id}"

        # 3. Object storage has the blob at the spec'd key.
        assert document.source_uri is not None
        storage = build_object_storage(
            provider="minio",
            bucket="sentinelrag-documents",
            region="us-east-1",
            endpoint=minio_with_bucket,
            access_key="minioadmin",
            secret_key="minioadmin",
            verify_ssl=False,
        )
        try:
            stored = await storage.get(document.source_uri)
            assert stored == body
        finally:
            await storage.close()

        # 4. Temporal client.start_workflow called with the typed payload.
        mock_temporal_client.start_workflow.assert_awaited_once()
        args, kwargs = mock_temporal_client.start_workflow.call_args
        assert args[0] == "IngestionWorkflow"
        # The payload is sent as a dict (model_dump(mode="json")). Reconstruct
        # via the contract to verify schema correctness.
        payload_dict = args[1]
        payload = IngestionWorkflowInput.model_validate(payload_dict)
        assert payload.tenant_id == tenant.id
        assert payload.collection_id == collection.id
        assert payload.document_id == document.id
        assert payload.storage_uri == document.source_uri
        assert payload.mime_type == "text/markdown"
        assert payload.embedding_model == "ollama/nomic-embed-text"
        assert kwargs["task_queue"] == "ingestion"
        assert kwargs["id"] == job.workflow_id

    async def test_idempotent_upload_returns_existing_indexed_document(
        self,
        admin_session: AsyncSession,
        tenant_session_factory,
        minio_with_bucket: str,
        mock_temporal_client,
        cleanup_db,
    ) -> None:
        tenant, user, collection = await self._seed_tenant_with_collection(admin_session)
        body = b"deduplication content"

        get_session = tenant_session_factory(tenant.id)

        # First upload.
        async for sess in get_session():
            storage = build_object_storage(
                provider="minio",
                bucket="sentinelrag-documents",
                region="us-east-1",
                endpoint=minio_with_bucket,
                access_key="minioadmin",
                secret_key="minioadmin",
                verify_ssl=False,
            )
            try:
                service = DocumentService(
                    sess,
                    storage=storage,
                    temporal_client=mock_temporal_client,
                    ingestion_task_queue="ingestion",
                    default_embedding_model="ollama/nomic-embed-text",
                )
                doc1, _ = await service.upload(
                    tenant_id=tenant.id,
                    created_by=user.id,
                    payload=DocumentCreate(collection_id=collection.id),
                    filename="dup.txt",
                    mime_type="text/plain",
                    body=body,
                )
            finally:
                await storage.close()

        # Mark the first document as indexed (simulating a completed workflow).
        async for sess in get_session():
            from sqlalchemy import text  # noqa: PLC0415

            await sess.execute(
                text("UPDATE documents SET status='indexed' WHERE id=:id"),
                {"id": str(doc1.id)},
            )

        mock_temporal_client.start_workflow.reset_mock()

        # Second upload of same content → should return doc1 + a no-op job.
        async for sess in get_session():
            storage = build_object_storage(
                provider="minio",
                bucket="sentinelrag-documents",
                region="us-east-1",
                endpoint=minio_with_bucket,
                access_key="minioadmin",
                secret_key="minioadmin",
                verify_ssl=False,
            )
            try:
                service = DocumentService(
                    sess,
                    storage=storage,
                    temporal_client=mock_temporal_client,
                    ingestion_task_queue="ingestion",
                    default_embedding_model="ollama/nomic-embed-text",
                )
                doc2, job2 = await service.upload(
                    tenant_id=tenant.id,
                    created_by=user.id,
                    payload=DocumentCreate(collection_id=collection.id),
                    filename="dup.txt",
                    mime_type="text/plain",
                    body=body,
                )
            finally:
                await storage.close()

        assert doc2.id == doc1.id
        assert job2.status == "completed"
        assert job2.input_source.get("deduplicated") is True
        # No workflow started for the dedup'd upload.
        mock_temporal_client.start_workflow.assert_not_awaited()
