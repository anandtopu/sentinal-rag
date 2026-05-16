"""Unit tests for ingestion-service source connectors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sentinelrag_ingestion_service.connectors import (
    ConnectorError,
    ConnectorRegistry,
    InlineTextConnector,
    LocalFileConnector,
    ObjectStorageConnector,
    UnsupportedSourceError,
)
from sentinelrag_ingestion_service.connectors.registry import build_default_registry
from sentinelrag_shared.object_storage.interface import ObjectMetadata, ObjectNotFoundError


class MemoryStorage:
    bucket = "docs"

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, ObjectMetadata]] = {}

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict[str, str] | None = None,
    ) -> ObjectMetadata:
        metadata = ObjectMetadata(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            last_modified=datetime.now(UTC),
            custom_metadata=custom_metadata or {},
        )
        self._objects[key] = (data, metadata)
        return metadata

    async def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError as exc:
            raise ObjectNotFoundError(key) from exc

    def get_stream(self, key: str) -> AsyncIterator[bytes]:
        async def stream() -> AsyncIterator[bytes]:
            yield await self.get(key)

        return stream()

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def head(self, key: str) -> ObjectMetadata:
        try:
            return self._objects[key][1]
        except KeyError as exc:
            raise ObjectNotFoundError(key) from exc

    def list_keys(self, prefix: str, *, page_size: int = 1000) -> AsyncIterator[str]:
        del page_size

        async def keys() -> AsyncIterator[str]:
            for key in sorted(self._objects):
                if key.startswith(prefix):
                    yield key

        return keys()

    async def presign_get_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        del expires_in_seconds
        return f"memory://{self.bucket}/{key}"

    async def close(self) -> None:
        return None


async def test_inline_text_connector_decodes_text_uri() -> None:
    connector = InlineTextConnector()

    document = await connector.fetch("text://hello%20runbook")

    assert document.content == b"hello runbook"
    assert document.filename == "inline.txt"
    assert document.mime_type == "text/plain; charset=utf-8"
    assert document.metadata == {"connector": "inline"}


async def test_local_file_connector_reads_allowed_file(tmp_path: Path) -> None:
    source = tmp_path / "policy.md"
    source.write_bytes(b"# Policy\n\nUse object storage.")

    connector = LocalFileConnector(allowed_roots=[tmp_path])
    document = await connector.fetch(str(source))

    assert document.content == b"# Policy\n\nUse object storage."
    assert document.filename == "policy.md"
    assert document.mime_type == "text/markdown"
    assert document.metadata["connector"] == "local_file"


async def test_local_file_connector_rejects_paths_outside_allowed_roots(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    source = denied / "secret.txt"
    source.write_text("not importable", encoding="utf-8")

    connector = LocalFileConnector(allowed_roots=[allowed])

    with pytest.raises(ConnectorError, match="outside allowed roots"):
        await connector.fetch(str(source))


async def test_object_storage_connector_fetches_s3_uri() -> None:
    storage = MemoryStorage()
    await storage.put(
        "tenant/documents/runbook.txt",
        b"deployment order",
        content_type="text/plain",
    )

    connector = ObjectStorageConnector(storage)
    document = await connector.fetch("s3://docs/tenant/documents/runbook.txt")

    assert document.content == b"deployment order"
    assert document.filename == "runbook.txt"
    assert document.mime_type == "text/plain"
    assert document.metadata["bucket"] == "docs"
    assert document.metadata["key"] == "tenant/documents/runbook.txt"


async def test_object_storage_connector_rejects_unconfigured_bucket() -> None:
    storage = MemoryStorage()
    connector = ObjectStorageConnector(storage)

    with pytest.raises(ConnectorError, match="does not match configured bucket"):
        await connector.fetch("s3://other-bucket/doc.txt")


async def test_registry_uses_first_supporting_connector() -> None:
    registry = ConnectorRegistry([InlineTextConnector()])

    document = await registry.fetch("inline://hello")

    assert document.content == b"hello"


async def test_registry_reports_unsupported_source() -> None:
    registry = ConnectorRegistry([InlineTextConnector()])

    with pytest.raises(UnsupportedSourceError):
        await registry.fetch("ftp://example.com/doc.txt")


def test_default_registry_lists_sample_connector_sources() -> None:
    storage = MemoryStorage()

    registry = build_default_registry(object_storage=storage)

    assert [connector.name for connector in registry.connectors] == [
        "inline",
        "http",
        "object_storage",
        "local_file",
    ]
