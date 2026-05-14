"""Focused unit coverage for backend service-layer decisions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from app.db.models import Document, EvaluationDataset, Role, Tenant
from app.schemas.documents import DocumentCreate
from app.schemas.evaluations import EvaluationRunCreate
from app.schemas.prompts import PromptTemplateCreate, PromptVersionCreate
from app.schemas.roles import RoleCreate, RoleUpdate
from app.schemas.tenants import TenantCreate, TenantUpdate
from app.schemas.users import UserCreate, UserUpdate
from app.services.document_service import DocumentService, _extension_for
from app.services.evaluation_service import EvaluationService
from app.services.prompt_service import DEFAULT_RAG_PROMPT_NAME, PromptService
from app.services.role_service import RoleService
from app.services.tenant_service import TenantService
from app.services.user_service import UserService
from sentinelrag_shared.errors.exceptions import (
    ConflictError,
    NotFoundError,
    RoleNotFoundError,
    TenantNotFoundError,
    UserNotFoundError,
    ValidationFailedError,
)


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[tuple[object, dict[str, Any] | None]] = []
        self.flushes = 0

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            cast(Any, obj).id = uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, statement: object, params: dict[str, Any] | None = None) -> None:
        self.executed.append((statement, params))


class FakeStorage:
    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes, dict[str, Any]]] = []

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict[str, str] | None = None,
    ) -> None:
        self.puts.append(
            (
                key,
                data,
                {"content_type": content_type, "custom_metadata": custom_metadata},
            )
        )


class FakeTemporal:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    async def start_workflow(self, workflow: str, payload: Any, **kwargs: Any) -> None:
        self.started.append({"workflow": workflow, "payload": payload, **kwargs})


@pytest.mark.unit
def test_extension_for_prefers_known_mime_then_filename_fallback() -> None:
    assert _extension_for("application/pdf", "ignored.bin") == "pdf"
    assert _extension_for("application/x-custom", "report.JSON") == "json"
    assert _extension_for("application/x-custom", "report") == "bin"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_upload_requires_existing_collection() -> None:
    service = DocumentService(
        FakeDb(),  # type: ignore[arg-type]
        storage=FakeStorage(),  # type: ignore[arg-type]
        temporal_client=FakeTemporal(),  # type: ignore[arg-type]
        ingestion_task_queue="ingestion",
        default_embedding_model="ollama/nomic-embed-text",
    )
    service.collections = SimpleNamespace(get=lambda _id: _async_value(None))

    with pytest.raises(NotFoundError):
        await service.upload(
            tenant_id=uuid4(),
            created_by=uuid4(),
            payload=DocumentCreate(collection_id=uuid4()),
            filename="doc.txt",
            mime_type="text/plain",
            body=b"hello",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_upload_deduplicates_indexed_content() -> None:
    db = FakeDb()
    tenant_id = uuid4()
    collection_id = uuid4()
    existing = Document(
        id=uuid4(),
        tenant_id=tenant_id,
        collection_id=collection_id,
        title="Existing",
        source_type="upload",
        source_uri="s3://existing",
        mime_type="text/plain",
        checksum="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        sensitivity_level="internal",
        metadata_={},
        status="indexed",
        created_by=uuid4(),
    )
    service = DocumentService(
        db,  # type: ignore[arg-type]
        storage=FakeStorage(),  # type: ignore[arg-type]
        temporal_client=FakeTemporal(),  # type: ignore[arg-type]
        ingestion_task_queue="ingestion",
        default_embedding_model="ollama/nomic-embed-text",
    )
    service.collections = SimpleNamespace(get=lambda _id: _async_value(object()))
    service.docs = SimpleNamespace(get_by_checksum=lambda **_kwargs: _async_value(existing))

    document, job = await service.upload(
        tenant_id=tenant_id,
        created_by=uuid4(),
        payload=DocumentCreate(collection_id=collection_id),
        filename="doc.txt",
        mime_type="text/plain",
        body=b"hello",
    )

    assert document is existing
    assert job.status == "completed"
    assert job.input_source["deduplicated"] is True
    assert len(db.added) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_document_upload_stores_blob_and_starts_ingestion_workflow() -> None:
    db = FakeDb()
    storage = FakeStorage()
    temporal = FakeTemporal()
    service = DocumentService(
        db,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        temporal_client=temporal,  # type: ignore[arg-type]
        ingestion_task_queue="ingestion",
        default_embedding_model="ollama/nomic-embed-text",
    )
    service.collections = SimpleNamespace(get=lambda _id: _async_value(object()))
    service.docs = SimpleNamespace(get_by_checksum=lambda **_kwargs: _async_value(None))

    document, job = await service.upload(
        tenant_id=uuid4(),
        created_by=uuid4(),
        payload=DocumentCreate(collection_id=uuid4(), title="Guide", metadata={"team": "sre"}),
        filename="guide.md",
        mime_type="text/markdown",
        body=b"# Guide",
    )

    assert document.title == "Guide"
    assert document.source_uri == storage.puts[0][0]
    assert job.status == "queued"
    assert job.workflow_id == f"ingest-{job.id}"
    assert temporal.started[0]["workflow"] == "IngestionWorkflow"
    assert temporal.started[0]["task_queue"] == "ingestion"
    assert temporal.started[0]["payload"]["metadata"] == {"team": "sre"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_service_rejects_duplicate_template() -> None:
    service = PromptService(FakeDb())  # type: ignore[arg-type]
    service.templates = SimpleNamespace(get_by_name=lambda _name: _async_value(object()))

    with pytest.raises(ConflictError):
        await service.create_template(
            tenant_id=uuid4(),
            created_by=uuid4(),
            payload=PromptTemplateCreate(name="rag", task_type="rag"),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_service_create_version_clears_existing_default() -> None:
    db = FakeDb()
    template_id = uuid4()
    service = PromptService(db)  # type: ignore[arg-type]
    service.templates = SimpleNamespace(get=lambda _id: _async_value(object()))
    service.versions = SimpleNamespace(latest_version_number=lambda _id: _async_value(2))

    version = await service.create_version(
        tenant_id=uuid4(),
        template_id=template_id,
        created_by=uuid4(),
        payload=PromptVersionCreate(
            system_prompt="system",
            user_prompt_template="{query}",
            set_as_default=True,
        ),
    )

    assert version.version_number == 3
    assert version.is_default is True
    assert db.executed
    assert db.executed[0][1] == {"tid": str(template_id)}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_service_seeds_default_rag_prompt() -> None:
    service = PromptService(FakeDb())  # type: ignore[arg-type]
    service.templates = SimpleNamespace(get_by_name=lambda _name: _async_value(None))

    version = await service.resolve_for_task(
        tenant_id=uuid4(),
        task_type=DEFAULT_RAG_PROMPT_NAME,
    )

    assert version.version_number == 1
    assert version.is_default is True
    assert "provided context" in version.system_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_service_start_run_requires_dataset() -> None:
    service = EvaluationService(FakeDb())  # type: ignore[arg-type]
    service.datasets = SimpleNamespace(get=lambda _id: _async_value(None))

    with pytest.raises(NotFoundError):
        await service.start_run(
            tenant_id=uuid4(),
            created_by=uuid4(),
            payload=EvaluationRunCreate(
                dataset_id=uuid4(),
                name="run",
                collection_ids=[uuid4()],
                model_config={},
            ),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_service_start_run_starts_temporal_workflow() -> None:
    temporal = FakeTemporal()
    dataset_id = uuid4()
    actor_id = uuid4()
    collection_id = uuid4()
    service = EvaluationService(
        FakeDb(),  # type: ignore[arg-type]
        temporal_client=temporal,  # type: ignore[arg-type]
    )
    service.datasets = SimpleNamespace(
        get=lambda _id: _async_value(EvaluationDataset(id=dataset_id))
    )

    run = await service.start_run(
        tenant_id=uuid4(),
        created_by=actor_id,
        payload=EvaluationRunCreate(
            dataset_id=dataset_id,
            name="nightly",
            collection_ids=[collection_id],
            retrieval_config={"mode": "hybrid"},
            model_config={"model": "ollama/llama3.1:8b"},
        ),
    )

    assert run.workflow_id == f"eval-{run.id}"
    assert run.retrieval_config["collection_ids"] == [str(collection_id)]
    assert temporal.started[0]["workflow"] == "EvaluationRunWorkflow"
    assert temporal.started[0]["payload"]["actor_user_id"] == str(actor_id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_service_aggregate_adds_case_total() -> None:
    run = SimpleNamespace(dataset_id=uuid4())
    service = EvaluationService(FakeDb())  # type: ignore[arg-type]
    service.runs = SimpleNamespace(get=lambda _id: _async_value(run))
    service.scores = SimpleNamespace(
        aggregate_for_run=lambda _id: _async_value({"cases_completed": 2})
    )
    service.cases = SimpleNamespace(count_for_dataset=lambda _id: _async_value(3))

    returned_run, aggregate = await service.aggregate_run(uuid4())

    assert returned_run is run
    assert aggregate["cases_total"] == 3
    assert aggregate["cases_completed"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_service_create_duplicate_slug_conflicts() -> None:
    service = TenantService(FakeDb())  # type: ignore[arg-type]
    service.repo = SimpleNamespace(get_by_slug=lambda _slug: _async_value(object()))

    with pytest.raises(ConflictError):
        await service.create(TenantCreate(name="Demo", slug="demo"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_service_update_mutates_optional_fields() -> None:
    tenant = Tenant(id=uuid4(), name="Old", slug="old", plan="developer", metadata_={})
    service = TenantService(FakeDb())  # type: ignore[arg-type]
    service.repo = SimpleNamespace(get=lambda _id: _async_value(tenant))

    updated = await service.update(
        tenant.id,
        TenantUpdate(name="New", plan="team", status="active", metadata={"tier": "gold"}),
    )

    assert updated.name == "New"
    assert updated.plan == "team"
    assert updated.status == "active"
    assert updated.metadata_ == {"tier": "gold"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_service_create_normalizes_email_and_rejects_duplicate() -> None:
    service = UserService(FakeDb())  # type: ignore[arg-type]
    service.repo = SimpleNamespace(get_by_email=lambda _email: _async_value(None))

    user = await service.create(
        tenant_id=uuid4(),
        payload=UserCreate(email="USER@EXAMPLE.COM", full_name="User"),
    )

    assert user.email == "user@example.com"

    service.repo = SimpleNamespace(get_by_email=lambda _email: _async_value(object()))
    with pytest.raises(ConflictError):
        await service.create(
            tenant_id=uuid4(),
            payload=UserCreate(email="user@example.com"),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_service_update_requires_user() -> None:
    service = UserService(FakeDb())  # type: ignore[arg-type]
    service.repo = SimpleNamespace(get=lambda _id: _async_value(None))

    with pytest.raises(UserNotFoundError):
        await service.update(uuid4(), UserUpdate(full_name="Missing"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_role_service_validates_permission_codes_before_create() -> None:
    service = RoleService(FakeDb())  # type: ignore[arg-type]
    service.permissions = SimpleNamespace(get_by_code=lambda _code: _async_value(None))

    with pytest.raises(ValidationFailedError):
        await service.create(
            tenant_id=uuid4(),
            payload=RoleCreate(name="reader", permission_codes=["missing"]),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_role_service_update_sets_permissions() -> None:
    role = Role(id=uuid4(), tenant_id=uuid4(), name="reader", description="old")
    set_calls: list[dict[str, Any]] = []
    service = RoleService(FakeDb())  # type: ignore[arg-type]
    service.repo = SimpleNamespace(
        get=lambda _id: _async_value(role),
        set_permissions=lambda **kwargs: _async_call(set_calls, kwargs),
    )
    service.permissions = SimpleNamespace(get_by_code=lambda _code: _async_value(object()))

    updated = await service.update(
        role.id,
        RoleUpdate(description="new", permission_codes=["documents:read"]),
    )

    assert updated.description == "new"
    assert set_calls == [{"role_id": role.id, "permission_codes": ["documents:read"]}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_and_role_get_missing_raise_domain_errors() -> None:
    tenant_service = TenantService(FakeDb())  # type: ignore[arg-type]
    tenant_service.repo = SimpleNamespace(get=lambda _id: _async_value(None))
    with pytest.raises(TenantNotFoundError):
        await tenant_service.get(uuid4())

    role_service = RoleService(FakeDb())  # type: ignore[arg-type]
    role_service.repo = SimpleNamespace(get=lambda _id: _async_value(None))

    with pytest.raises(RoleNotFoundError):
        await role_service.get(uuid4())


async def _async_value(value: object) -> object:
    return value


async def _async_call(calls: list[dict[str, Any]], value: dict[str, Any]) -> None:
    calls.append(value)
