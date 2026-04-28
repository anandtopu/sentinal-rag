"""Object storage abstraction.

Single ``ObjectStorage`` interface implemented by S3 (covers MinIO via
endpoint_url override), GCS, and Azure Blob. The factory selects the
implementation from configuration at process startup.

Production-rule: never import boto3 / google-cloud-storage / azure-storage
from service code. Always go through the interface.
"""

from sentinelrag_shared.object_storage.factory import build_object_storage
from sentinelrag_shared.object_storage.interface import (
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
)

__all__ = [
    "ObjectMetadata",
    "ObjectNotFoundError",
    "ObjectStorage",
    "ObjectStorageError",
    "build_object_storage",
]
