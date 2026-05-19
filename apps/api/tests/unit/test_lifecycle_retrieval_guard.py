"""R6.S3: startup guard for RETRIEVAL_TRANSPORT=http without a token.

The remediation-stream R4 handoff flagged that this combination would
let the API boot, accept traffic, and 503 every /query. The guard
makes the misconfiguration fail at process start instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from app.lifecycle import _build_retrieval_client
from app.services.rag.client import HttpRetrievalClient


class _Recorder:
    """Stand-in for structlog logger — captures `.info` / `.warning` calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("warning", event, kwargs))


def _settings(
    *,
    transport: str,
    token: str = "",
    url: str = "http://retrieval.test",
) -> Any:
    return SimpleNamespace(
        retrieval_transport=transport,
        retrieval_service_url=url,
        retrieval_service_token=token,
        retrieval_service_timeout_seconds=5.0,
    )


@pytest.mark.unit
def test_in_process_transport_returns_none() -> None:
    log = _Recorder()
    client = _build_retrieval_client(settings=_settings(transport="in-process"), log=log)
    assert client is None
    assert any(c[1] == "retrieval.transport" for c in log.calls)


@pytest.mark.unit
def test_http_transport_with_token_builds_client() -> None:
    log = _Recorder()
    client = _build_retrieval_client(
        settings=_settings(transport="http", token="real-secret"),
        log=log,
    )
    assert isinstance(client, HttpRetrievalClient)


@pytest.mark.unit
def test_http_transport_without_token_fails_loud() -> None:
    """The misconfiguration the R4 handoff flagged."""
    log = _Recorder()
    with pytest.raises(RuntimeError, match="RETRIEVAL_SERVICE_TOKEN is empty"):
        _build_retrieval_client(
            settings=_settings(transport="http", token=""),
            log=log,
        )


@pytest.mark.unit
def test_unknown_transport_fails_at_startup() -> None:
    """Pydantic's Literal narrows this away in practice; defensive guard fires."""
    log = _Recorder()
    with pytest.raises(RuntimeError, match="Unknown RETRIEVAL_TRANSPORT"):
        _build_retrieval_client(settings=_settings(transport="websockets"), log=log)
