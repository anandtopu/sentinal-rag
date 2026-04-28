"""ObjectStorage protocol + shared types.

Async-only by convention. All implementations return bytes for ``get`` and
take bytes (or an async iterator) for ``put``. Stream support is intentionally
deferred until profiling shows it matters — most documents are <100MB and
fit in memory comfortably.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ObjectStorageError(Exception):
    """Base class for object-storage errors."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised when ``get`` is called with a key that doesn't exist."""


@dataclass(slots=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    content_type: str | None = None
    last_modified: datetime | None = None
    etag: str | None = None
    custom_metadata: dict[str, str] = field(default_factory=dict)


class ObjectStorage(Protocol):
    """Async object-storage operations.

    Implementations: ``S3Storage`` (also handles MinIO), ``GcsStorage``,
    ``AzureBlobStorage``.
    """

    bucket: str

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        custom_metadata: dict[str, str] | None = None,
    ) -> ObjectMetadata:
        """Upload ``data`` to ``key``. Overwrites if it exists."""
        ...

    async def get(self, key: str) -> bytes:
        """Read object bytes. Raises :class:`ObjectNotFoundError` if missing."""
        ...

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        """Stream object bytes in chunks. Used for large blobs."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def head(self, key: str) -> ObjectMetadata:
        """Fetch object metadata without downloading the body."""
        ...

    async def presign_get_url(self, key: str, *, expires_in_seconds: int = 3600) -> str:
        """Return a signed URL for time-limited public access to the object."""
        ...

    async def close(self) -> None: ...
