"""Unit coverage for query model access classification."""

from __future__ import annotations

import pytest
from app.api.v1.routes.query import requires_cloud_model_permission


@pytest.mark.unit
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("ollama/llama3.1:8b", False),
        ("openai/gpt-4o-mini", True),
        ("anthropic/claude-3-5-haiku", True),
    ],
)
def test_requires_cloud_model_permission(model: str, expected: bool) -> None:
    assert requires_cloud_model_permission(model) is expected
