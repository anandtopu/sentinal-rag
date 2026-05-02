"""Google Cloud Storage implementation of the ObjectStorage protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, timedelta
from typing import cast

from google.api_core.exceptions import NotFound
from google.cloud import storage

from sentinelrag_shared.object_storage.interface import (
    ObjectMetadata,
    ObjectNotFoundError,
)


class GcsStorage:
    """Async wrapper around google-cloud-storage.

    The official GCS client is synchronous. These methods offload blocking
    calls with ``asyncio.to_thread`` so callers can keep the shared async
    storage interface used by API routes and Temporal activities.
    """

    def __init__(self, *, bucket: str, project: str | None = None) -> None:
        self.bucket = bucket
        self._client = storage.Client(project=project)
        self._bucket = self._client.bucket(bucket)

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict[str, str] | None = None,
    ) -> ObjectMetadata:
        def _put() -> ObjectMetadata:
            blob = self._bucket.blob(key)
            blob.metadata = custom_metadata
            blob.upload_from_string(
                data,
                content_type=content_type or "application/octet-stream",
            )
            blob.reload()
            return _metadata_from_blob(blob, key=key)

        return await asyncio.to_thread(_put)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            blob = self._bucket.blob(key)
            try:
                return blob.download_as_bytes()
            except NotFound as exc:
                raise ObjectNotFoundError(key) from exc

        return await asyncio.to_thread(_get)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        yield await self.get(key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._bucket.blob(key).exists)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            try:
                self._bucket.blob(key).delete()
            except NotFound:
                return

        await asyncio.to_thread(_delete)

    async def head(self, key: str) -> ObjectMetadata:
        def _head() -> ObjectMetadata:
            blob = self._bucket.blob(key)
            try:
                blob.reload()
            except NotFound as exc:
                raise ObjectNotFoundError(key) from exc
            return _metadata_from_blob(blob, key=key)

        return await asyncio.to_thread(_head)

    async def list_keys(
        self, prefix: str, *, page_size: int = 1000
    ) -> AsyncIterator[str]:
        def _list() -> list[str]:
            return [
                cast(str, blob.name)
                for blob in self._client.list_blobs(
                    self.bucket,
                    prefix=prefix,
                    page_size=page_size,
                )
            ]

        for key in await asyncio.to_thread(_list):
            yield key

    async def presign_get_url(
        self, key: str, *, expires_in_seconds: int = 3600
    ) -> str:
        def _sign() -> str:
            blob = self._bucket.blob(key)
            return blob.generate_signed_url(
                expiration=timedelta(seconds=expires_in_seconds),
                method="GET",
            )

        return await asyncio.to_thread(_sign)

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)


def _metadata_from_blob(blob: storage.Blob, *, key: str | None = None) -> ObjectMetadata:
    updated = blob.updated
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return ObjectMetadata(
        key=key or cast(str, blob.name),
        size_bytes=int(blob.size or 0),
        content_type=blob.content_type,
        last_modified=updated,
        etag=cast(str | None, blob.etag),
        custom_metadata=dict(cast(dict[str, str] | None, blob.metadata) or {}),
    )
