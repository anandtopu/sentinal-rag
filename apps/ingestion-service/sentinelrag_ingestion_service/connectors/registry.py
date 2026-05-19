"""Connector registry factory."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sentinelrag_ingestion_service.connectors.base import SourceConnector
from sentinelrag_ingestion_service.connectors.http import HttpConnector
from sentinelrag_ingestion_service.connectors.inline import InlineTextConnector
from sentinelrag_ingestion_service.connectors.localfile import LocalFileConnector
from sentinelrag_ingestion_service.connectors.objectstorage import ObjectStorageConnector


class ConnectorRegistry:
    def __init__(self, connectors: Sequence[SourceConnector] | None = None) -> None:
        self._connectors: list[SourceConnector] = list(connectors) if connectors is not None else []

    def register(self, connector: SourceConnector) -> None:
        self._connectors.append(connector)

    def extend(self, connectors: Iterable[SourceConnector]) -> None:
        self._connectors.extend(connectors)

    @property
    def connectors(self) -> Sequence[SourceConnector]:
        return tuple(self._connectors)


def build_default_registry() -> ConnectorRegistry:
    connectors: list[SourceConnector] = [
        InlineTextConnector(),
        HttpConnector(),
        LocalFileConnector(),
        ObjectStorageConnector(),
    ]
    return ConnectorRegistry(connectors)
