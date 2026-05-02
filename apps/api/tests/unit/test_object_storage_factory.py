"""Unit coverage for object-storage provider selection."""

from __future__ import annotations

from typing import Any

import pytest
from sentinelrag_shared.object_storage import factory


class _FakeGcsStorage:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.mark.unit
def test_build_object_storage_supports_gcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "GcsStorage", _FakeGcsStorage)

    storage = factory.build_object_storage(
        provider="gcs",
        bucket="sentinelrag-dev-documents",
        gcp_project="sentinelrag-dev",
    )

    assert isinstance(storage, _FakeGcsStorage)
    assert storage.kwargs == {
        "bucket": "sentinelrag-dev-documents",
        "project": "sentinelrag-dev",
    }
