"""Compatibility imports for the legacy ``app.connectors`` path.

The installable ingestion-service package is ``sentinelrag_ingestion_service``.
New code should import from ``sentinelrag_ingestion_service.connectors``.
"""

from sentinelrag_ingestion_service.connectors import (
    ConnectorError,
    ConnectorRegistry,
    FetchedDocument,
    HttpConnector,
    InlineTextConnector,
    LocalFileConnector,
    ObjectStorageConnector,
    SourceConnector,
    UnsupportedSourceError,
)
from sentinelrag_ingestion_service.connectors.registry import build_default_registry

__all__ = [
    "ConnectorError",
    "ConnectorRegistry",
    "FetchedDocument",
    "HttpConnector",
    "InlineTextConnector",
    "LocalFileConnector",
    "ObjectStorageConnector",
    "SourceConnector",
    "UnsupportedSourceError",
    "build_default_registry",
]
