"""Connector registry factory."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import cast

from sentinelrag_shared.object_storage.interface import ObjectStorage

from sentinelrag_ingestion_service.connectors.base import (
    SourceConnector,
    UnsupportedSourceError,
)
from sentinelrag_ingestion_service.connectors.http import HttpConnector
from sentinelrag_ingestion_service.connectors.inline import InlineTextConnector
from sentinelrag_ingestion_service.connectors.local_file import LocalFileConnector
from sentinelrag_ingestion_service.connectors.object_storage import ObjectStorageConnector


class ConnectorRegistry:
    def __init__(self, connectors: Sequence[SourceConnector] | None = None) -> None:
        self._connectors: list[SourceConnector] = (
            list(connectors) if connectors is not None else []
        )

    def register(self, connector: SourceConnector) -> None:
        self._connectors.append(connector)

    def extend(self, connectors: Iterable[SourceConnector]) -> None:
        self._connectors.extend(connectors)

    @property
    def connectors(self) -> Sequence[SourceConnector]:
        return tuple(self._connectors)

    def get_connector(self, source_uri: str) -> SourceConnector:
        if source_uri.startswith("inline:"):
            for connector in self._connectors:
                if isinstance(connector, InlineTextConnector):
                    return connector

        if source_uri.startswith("http://") or source_uri.startswith("https://"):
            for connector in self._connectors:
                if isinstance(connector, HttpConnector):
                    return connector

        if (
            source_uri.startswith("s3://")
            or source_uri.startswith("gs://")
            or source_uri.startswith("az://")
        ):
            for connector in self._connectors:
                if isinstance(connector, ObjectStorageConnector):
                    return connector

        for connector in self._connectors:
            if isinstance(connector, LocalFileConnector):
                return connector

        raise UnsupportedSourceError(f"No connector registered for source URI: {source_uri}")

    async def fetch(self, source_uri: str) -> object:
        connector = self.get_connector(source_uri)
        return await connector.fetch(source_uri)


def build_default_registry(
    object_storage: ObjectStorage | None = None,
) -> ConnectorRegistry:
    connectors = cast(
        list[SourceConnector],
        [
            InlineTextConnector(),
            HttpConnector(),
        ],
    )
    if object_storage is not None:
        connectors.append(cast(SourceConnector, ObjectStorageConnector(object_storage)))
    connectors.append(LocalFileConnector())
    return ConnectorRegistry(connectors)
