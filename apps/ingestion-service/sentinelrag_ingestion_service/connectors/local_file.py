"""Local filesystem source connector."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from sentinelrag_ingestion_service.connectors.base import ConnectorError, FetchedDocument


class LocalFileConnector:
    """Fetch documents from local paths.

    This connector is intended for local smoke tests and controlled import
    jobs. In production, prefer object-storage URIs produced by the API upload
    path so tenant authorization and audit remain centralized.
    """

    name = "local_file"

    def __init__(self, *, allowed_roots: list[Path] | None = None) -> None:
        self._allowed_roots = [root.resolve() for root in allowed_roots or []]

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        return parsed.scheme in {"file", ""}

    async def fetch(self, source_uri: str) -> FetchedDocument:
        path = self._path_from_uri(source_uri)
        return await asyncio.to_thread(self._fetch_sync, path, source_uri)

    def _path_from_uri(self, source_uri: str) -> Path:
        parsed = urlparse(source_uri)
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise ConnectorError(f"Remote file URI hosts are not supported: {source_uri}")
            path = Path(unquote(parsed.path))
        else:
            path = Path(source_uri)
        return path.expanduser().resolve()

    def _fetch_sync(self, path: Path, source_uri: str) -> FetchedDocument:
        self._assert_allowed(path)
        if not path.is_file():
            raise ConnectorError(f"Local source is not a file: {path}")

        content = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FetchedDocument(
            content=content,
            source_uri=source_uri,
            filename=path.name,
            mime_type=mime_type,
            metadata={
                "connector": self.name,
                "path": str(path),
                "content_length": str(len(content)),
            },
        )

    def _assert_allowed(self, path: Path) -> None:
        if not self._allowed_roots:
            return
        if not any(path == root or root in path.parents for root in self._allowed_roots):
            roots = ", ".join(str(root) for root in self._allowed_roots)
            raise ConnectorError(f"Local source path is outside allowed roots ({roots}): {path}")
