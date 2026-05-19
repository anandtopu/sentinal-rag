from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


def _metadata_factory() -> dict[str, Any]:
    return {}


class ConnectorError(RuntimeError):
    """Base connector error."""


class UnsupportedSourceError(ConnectorError):
    """Raised when no connector can handle a source URI."""


@dataclass(slots=True)
class FetchedDocument:
    source_uri: str
    content: bytes
    filename: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=_metadata_factory)


SourceDocument = FetchedDocument


class SourceConnector(Protocol):
    async def fetch(self, source_uri: str) -> FetchedDocument: ...
