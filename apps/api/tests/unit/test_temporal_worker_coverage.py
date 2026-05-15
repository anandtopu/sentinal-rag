"""Unit coverage for Temporal worker workflow and activity edge cases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from sentinelrag_worker.activities import evaluation as eval_activities
from sentinelrag_worker.activities import ingestion as ingestion_activities
from sentinelrag_worker.workflows import evaluation as eval_workflow
from sentinelrag_worker.workflows import ingestion as ingestion_workflow


class FakeStorage:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.puts: list[tuple[str, bytes, dict[str, Any]]] = []
        self.closed = False

    async def get(self, _key: str) -> bytes:
        return self.data

    async def put(self, key: str, data: bytes, **kwargs: Any) -> None:
        self.puts.append((key, data, kwargs))

    async def close(self) -> None:
        self.closed = True


class FakeDbResult:
    def __init__(
        self,
        *,
        first_row: object | None = None,
        scalar: object | None = None,
        rows: list[object] | None = None,
        rowcount: int = 1,
    ) -> None:
        self.first_row = first_row
        self.scalar = scalar
        self.rows = rows or []
        self.rowcount = rowcount

    def first(self) -> object | None:
        return self.first_row

    def scalar_one(self) -> object:
        return self.scalar

    def fetchall(self) -> list[object]:
        return self.rows


class FakeSession:
    def __init__(self, results: list[FakeDbResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(
        self, statement: object, params: dict[str, Any] | None = None
    ) -> FakeDbResult:
        self.calls.append((str(statement), params))
        return self.results.pop(0)


@pytest.mark.unit
def test_activity_uuid_and_vector_helpers_are_deterministic() -> None:
    value = uuid4()

    assert ingestion_activities._as_uuid(str(value)) == value
    assert ingestion_activities._as_uuid(value) == value
    assert ingestion_activities._format_vector([1, "2.5"]) == "[1.0,2.5]"  # type: ignore[list-item]
    assert (
        ingestion_activities._raw_text_key("tenant/documents/doc/versions/v/original.txt")
        == "tenant/documents/doc/versions/v/raw.txt"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_download_and_hash_closes_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = FakeStorage(b"hello")
    monkeypatch.setattr(ingestion_activities, "_build_storage", lambda: storage)

    result = await ingestion_activities.download_and_hash(str(uuid4()), "tenant/doc.txt")

    assert result["content_hash"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert result["size_bytes"] == "5"
    assert storage.closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_document_version_returns_existing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_version_id = uuid4()
    session = FakeSession(
        [FakeDbResult(first_row=(existing_version_id,))]
    )

    monkeypatch.setattr(
        ingestion_activities,
        "_session_for_tenant",
        _session_factory(session),
    )

    version_id = await ingestion_activities.upsert_document_version(
        str(uuid4()),
        str(uuid4()),
        "hash",
        "s3://doc",
    )

    assert version_id == str(existing_version_id)
    assert len(session.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_document_version_inserts_next_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_version_id = uuid4()
    session = FakeSession(
        [
            FakeDbResult(first_row=None),
            FakeDbResult(scalar=4),
            FakeDbResult(scalar=new_version_id),
        ]
    )
    monkeypatch.setattr(
        ingestion_activities,
        "_session_for_tenant",
        _session_factory(session),
    )

    version_id = await ingestion_activities.upsert_document_version(
        str(uuid4()),
        str(uuid4()),
        "hash",
        "s3://doc",
    )

    assert version_id == str(new_version_id)
    assert session.calls[2][1]["v"] == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_mark_run_running_raises_when_row_not_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([FakeDbResult(rowcount=0)])
    monkeypatch.setattr(eval_activities, "_session_for_tenant", _session_factory(session))

    with pytest.raises(RuntimeError, match="not visible"):
        await eval_activities.mark_run_running(str(uuid4()), str(uuid4()))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_list_case_ids_returns_ordered_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case_ids = [uuid4(), uuid4()]
    rows = [(case_ids[0],), (case_ids[1],)]
    session = FakeSession([FakeDbResult(rows=rows)])
    monkeypatch.setattr(eval_activities, "_session_for_tenant", _session_factory(session))

    result = await eval_activities.list_case_ids(str(uuid4()), str(uuid4()))

    assert result == [str(case_ids[0]), str(case_ids[1])]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingestion_mark_job_failed_also_marks_document_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([FakeDbResult(), FakeDbResult()])
    monkeypatch.setattr(
        ingestion_activities,
        "_session_for_tenant",
        _session_factory(session),
    )

    await ingestion_activities.mark_job_failed(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "parse failed",
    )

    assert "UPDATE ingestion_jobs" in session.calls[0][0]
    assert "UPDATE documents SET status='failed'" in session.calls[1][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_record_case_failure_upserts_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([FakeDbResult()])
    monkeypatch.setattr(eval_activities, "_session_for_tenant", _session_factory(session))

    await eval_activities.record_case_failure(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "provider timeout",
    )

    assert "ON CONFLICT" in session.calls[0][0]
    assert session.calls[0][1]["error"] == "provider timeout"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingestion_workflow_marks_job_failed_when_activity_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[Any] | None]] = []

    async def fake_execute_activity(
        fn: object, *_, args: list[Any] | None = None, **__: object
    ) -> Any:
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "download_and_hash":
            return {"content_hash": "hash"}
        if name == "upsert_document_version":
            return str(uuid4())
        if name == "parse_document":
            raise RuntimeError("parse failed")
        return None

    monkeypatch.setattr(ingestion_workflow.workflow, "execute_activity", fake_execute_activity)

    payload = {
        "job_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "collection_id": str(uuid4()),
        "document_id": str(uuid4()),
        "storage_uri": "s3://doc",
        "mime_type": "text/plain",
        "embedding_model": "ollama/nomic-embed-text",
    }

    with pytest.raises(RuntimeError, match="parse failed"):
        await ingestion_workflow.IngestionWorkflow().run(payload)

    assert calls[-1][0] == "mark_job_failed"
    assert calls[-1][1][3] == "parse failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluation_workflow_counts_failed_cases_and_finalizes_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalized: dict[str, Any] = {}

    async def fake_execute_activity(
        fn: object,
        *_args: object,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        **_options: object,
    ) -> Any:
        name = getattr(fn, "__name__", "")
        if name == "list_case_ids":
            return ["case-ok", "case-fail"]
        if name == "score_case" and kwargs and kwargs["case_id"] == "case-fail":
            raise RuntimeError("case failed")
        if name == "finalize_run":
            finalized["args"] = args
        return None

    monkeypatch.setattr(eval_workflow.workflow, "execute_activity", fake_execute_activity)
    run_id = uuid4()
    payload = {
        "evaluation_run_id": str(run_id),
        "tenant_id": str(uuid4()),
        "dataset_id": str(uuid4()),
        "collection_ids": [str(uuid4())],
        "model_config": {},
        "retrieval_config": {},
    }

    result = await eval_workflow.EvaluationRunWorkflow().run(payload)

    assert result["evaluation_run_id"] == str(run_id)
    assert result["cases_completed"] == 1
    assert result["cases_failed"] == 1
    assert finalized["args"][2] == "failed"


def _session_factory(session: FakeSession) -> object:
    @asynccontextmanager
    async def factory(_tenant_id: object) -> AsyncIterator[FakeSession]:
        yield session

    return factory
