"""Connector registry factory."""

from __future__ import annotations

from pathlib import Path

from sentinelrag_shared.object_storage.interface import ObjectStorage

from sentinelrag_ingestion_service.connectors.base import ConnectorRegistry
from sentinelrag_ingestion_service.connectors.http import HttpConnector
from sentinelrag_ingestion_service.connectors.inline import InlineTextConnector
from sentinelrag_ingestion_service.connectors.local_file import LocalFileConnector
from sentinelrag_ingestion_service.connectors.object_storage import ObjectStorageConnector


def build_default_registry(
    *,
    object_storage: ObjectStorage | None = None,
    local_allowed_roots: list[Path] | None = None,
) -> ConnectorRegistry:
    """Build the standard connector set for ingestion-service."""

    connectors = [
        InlineTextConnector(),
        HttpConnector(),
        LocalFileConnector(allowed_roots=local_allowed_roots),
    ]
    if object_storage is not None:
        connectors.insert(2, ObjectStorageConnector(object_storage))
    return ConnectorRegistry(connectors)
