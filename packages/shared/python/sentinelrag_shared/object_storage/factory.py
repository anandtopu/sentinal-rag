"""Factory selecting the right ObjectStorage implementation from settings.

Settings shape (env vars or pydantic Settings model):

    OBJECT_STORAGE_PROVIDER         s3 | minio | gcs | azure
    OBJECT_STORAGE_BUCKET           bucket / container name
    OBJECT_STORAGE_REGION           AWS region or equivalent
    OBJECT_STORAGE_ENDPOINT         endpoint_url (MinIO / S3-compatible)
    OBJECT_STORAGE_ACCESS_KEY       (S3, Azure)
    OBJECT_STORAGE_SECRET_KEY       (S3, Azure)
    OBJECT_STORAGE_GCP_PROJECT      (GCS)

GCS and Azure adapters are stubbed in this file as ``NotImplementedError``
in v1; ADR-0011 commits us to AWS primary for live deploy, so they're
populated as part of Phase 8 (multi-cloud + scale).
"""

from __future__ import annotations

from sentinelrag_shared.object_storage.interface import ObjectStorage
from sentinelrag_shared.object_storage.s3 import S3Storage


def build_object_storage(
    *,
    provider: str,
    bucket: str,
    region: str = "us-east-1",
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    verify_ssl: bool = True,
) -> ObjectStorage:
    """Construct the configured ObjectStorage adapter."""
    provider_lower = provider.lower()

    if provider_lower in {"s3", "minio"}:
        return S3Storage(
            bucket=bucket,
            region=region,
            endpoint_url=endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
            verify_ssl=verify_ssl and provider_lower != "minio",
        )

    if provider_lower == "gcs":
        msg = "GCS object-storage adapter is implemented in Phase 8."
        raise NotImplementedError(msg)

    if provider_lower == "azure":
        msg = "Azure Blob object-storage adapter is documented in ADR-0011 only."
        raise NotImplementedError(msg)

    msg = f"Unknown object storage provider: {provider!r}"
    raise ValueError(msg)
