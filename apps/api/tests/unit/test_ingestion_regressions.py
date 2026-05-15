"""Regression tests for ingestion orchestration gaps."""

from __future__ import annotations

import pytest
from app.main import create_app


@pytest.mark.unit
def test_ingestion_cancel_route_is_registered() -> None:
    app = create_app()
    methods_by_path = {
        route.path: getattr(route, "methods", set())
        for route in app.routes
        if route.path == "/api/v1/ingestion/jobs/{job_id}/cancel"
    }

    assert "POST" in methods_by_path["/api/v1/ingestion/jobs/{job_id}/cancel"]
