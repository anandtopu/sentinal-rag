"""Common source-connector contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ConnectorError(Exception):
    """Base class for connector failures."""


class UnsupportedSourceError(ConnectorError):
    """Raised when no registered connector can handle a source URI."""


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    """Raw document payload fetched from an external source."""

    content: bytes
    source_uri: str
    filename: str
    mime_type: str
    metadata: dict[str, str] = field(default_factory=dict)


class SourceConnector(Protocol):
    """Fetch raw bytes from one source family."""

    name: str

    def supports(self, source_uri: str) -> bool:
        """Return true when this connector owns ``source_uri``."""
        ...

    async def fetch(self, source_uri: str) -> FetchedDocument:
        """Fetch raw document bytes and source metadata."""
        ...


class ConnectorRegistry:
    """Ordered connector registry.

    The first connector that reports support for a source URI is used. Keep
    specific connectors before broad catch-alls when adding new sources.
    """

    def __init__(self, connectors: list[SourceConnector] | None = None) -> None:
        self._connectors = connectors or []

    def register(self, connector: SourceConnector) -> None:
        self._connectors.append(connector)

    @property
    def connectors(self) -> tuple[SourceConnector, ...]:
        return tuple(self._connectors)

    async def fetch(self, source_uri: str) -> FetchedDocument:
        for connector in self._connectors:
            if connector.supports(source_uri):
                return await connector.fetch(source_uri)
        raise UnsupportedSourceError(f"No connector registered for source URI: {source_uri}")
