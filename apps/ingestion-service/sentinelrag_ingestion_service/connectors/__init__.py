"""Source connectors for ingestion-service.

Connectors normalize external sources into bytes + metadata. They do not parse,
chunk, embed, or persist rows; those steps remain in the Temporal ingestion
workflow and shared packages.
"""

from sentinelrag_ingestion_service.connectors.base import (
    ConnectorError,
    ConnectorRegistry,
    FetchedDocument,
    SourceConnector,
    UnsupportedSourceError,
)
from sentinelrag_ingestion_service.connectors.http import HttpConnector
from sentinelrag_ingestion_service.connectors.inline import InlineTextConnector
from sentinelrag_ingestion_service.connectors.local_file import LocalFileConnector
from sentinelrag_ingestion_service.connectors.object_storage import ObjectStorageConnector

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
]
