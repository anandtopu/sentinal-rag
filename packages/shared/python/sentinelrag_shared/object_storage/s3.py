"""S3 (and MinIO) implementation of ObjectStorage.

Uses ``aioboto3`` for native async S3 calls. MinIO is supported by passing
the MinIO endpoint URL as ``endpoint_url`` and disabling SSL verification
for local dev.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from sentinelrag_shared.object_storage.interface import (
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
)


class S3Storage(ObjectStorage):
    """S3-compatible object storage. Works with AWS S3 and MinIO."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self.bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._verify_ssl = verify_ssl
        self._session = aioboto3.Session()

    def _client_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"region_name": self._region, "verify": self._verify_ssl}
        if self._endpoint_url:
            kw["endpoint_url"] = self._endpoint_url
        if self._access_key_id:
            kw["aws_access_key_id"] = self._access_key_id
        if self._secret_access_key:
            kw["aws_secret_access_key"] = self._secret_access_key
        return kw

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict[str, str] | None = None,
    ) -> ObjectMetadata:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            extra: dict[str, Any] = {}
            if content_type:
                extra["ContentType"] = content_type
            if custom_metadata:
                extra["Metadata"] = custom_metadata
            await s3.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return ObjectMetadata(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            last_modified=datetime.now(UTC),
            custom_metadata=custom_metadata or {},
        )

    async def get(self, key: str) -> bytes:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    raise ObjectNotFoundError(key) from exc
                raise ObjectStorageError(str(exc)) from exc
            return await response["Body"].read()

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    raise ObjectNotFoundError(key) from exc
                raise ObjectStorageError(str(exc)) from exc
            async for chunk in response["Body"].iter_chunks(64 * 1024):
                yield chunk

    async def exists(self, key: str) -> bool:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            try:
                await s3.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] in {"404", "NoSuchKey"}:
                    return False
                raise ObjectStorageError(str(exc)) from exc
            return True

    async def delete(self, key: str) -> None:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            await s3.delete_object(Bucket=self.bucket, Key=key)

    async def head(self, key: str) -> ObjectMetadata:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            try:
                response = await s3.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response["Error"]["Code"] in {"404", "NoSuchKey"}:
                    raise ObjectNotFoundError(key) from exc
                raise ObjectStorageError(str(exc)) from exc
        return ObjectMetadata(
            key=key,
            size_bytes=response.get("ContentLength", 0),
            content_type=response.get("ContentType"),
            last_modified=response.get("LastModified"),
            etag=response.get("ETag"),
            custom_metadata=response.get("Metadata", {}),
        )

    async def presign_get_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )

    async def close(self) -> None:
        # aioboto3 sessions are per-call; nothing persistent to close.
        return None
