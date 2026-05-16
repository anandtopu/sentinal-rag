"""Object-storage source connector."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from sentinelrag_shared.object_storage.interface import ObjectMetadata, ObjectStorage

from sentinelrag_ingestion_service.connectors.base import ConnectorError, FetchedDocument


class ObjectStorageConnector:
    """Fetch documents from S3/GCS/MinIO-style object-storage URIs.

    The connector delegates the actual read to the shared ``ObjectStorage``
    adapter so cloud-specific clients stay behind the existing abstraction.
    """

    name = "object_storage"

    def __init__(self, storage: ObjectStorage, *, schemes: set[str] | None = None) -> None:
        self._storage = storage
        self._schemes = schemes or {"s3", "gs", "minio"}

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        return parsed.scheme in self._schemes

    async def fetch(self, source_uri: str) -> FetchedDocument:
        parsed = urlparse(source_uri)
        if not parsed.netloc:
            raise ConnectorError(f"Object-storage URI must include a bucket: {source_uri}")

        key = unquote(parsed.path.lstrip("/"))
        if not key:
            raise ConnectorError(f"Object-storage URI must include an object key: {source_uri}")

        if parsed.netloc != self._storage.bucket:
            raise ConnectorError(
                f"Object-storage URI bucket {parsed.netloc!r} does not match "
                f"configured bucket {self._storage.bucket!r}"
            )

        content = await self._storage.get(key)
        filename = PurePosixPath(key).name or "object"
        head = await self._safe_head(key)
        mime_type = (
            head.content_type
            if head and head.content_type
            else mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )
        metadata = {"connector": self.name, "bucket": parsed.netloc, "key": key}
        if head and head.etag:
            metadata["etag"] = head.etag

        return FetchedDocument(
            content=content,
            source_uri=source_uri,
            filename=filename,
            mime_type=mime_type,
            metadata=metadata,
        )

    async def _safe_head(self, key: str) -> ObjectMetadata | None:
        try:
            return await self._storage.head(key)
        except Exception:
            return None
