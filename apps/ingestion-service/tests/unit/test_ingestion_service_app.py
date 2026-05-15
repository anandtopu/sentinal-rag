"""Unit tests for the standalone ingestion service app."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sentinelrag_ingestion_service.main import app


def test_health_endpoint_reports_service_name() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sentinelrag-ingestion-service",
    }


def test_capabilities_endpoint_lists_supported_strategies() -> None:
    client = TestClient(app)

    response = client.get("/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parsing_strategies"] == ["fast", "hi_res", "ocr_only", "auto"]
    assert {"semantic", "sliding_window", "structure_aware"}.issubset(
        set(payload["chunking_strategies"])
    )
