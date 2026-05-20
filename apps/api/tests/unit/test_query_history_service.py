"""Unit tests for QueryHistoryService (BACKLOG B10 #3).

Covers the row→QuerySessionListItem mapping (null grounding/model, float
coercion, abstain status) with a duck-typed fake repository — no Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from app.services.query_history_service import QueryHistoryService
from sqlalchemy.ext.asyncio import AsyncSession


class FakeRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.args: dict[str, Any] | None = None

    async def list_recent(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        self.args = {"limit": limit, "offset": offset}
        return self._rows


def _service(rows: list[dict[str, Any]]) -> QueryHistoryService:
    svc = QueryHistoryService(db=cast(AsyncSession, object()))
    svc.queries = cast(Any, FakeRepo(rows))
    return svc


def _row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "query_text": "What does the runbook say about pgvector rebuilds?",
        "status": "completed",
        "latency_ms": 312,
        "created_at": datetime.now(UTC),
        "grounding_score": 0.94,
        "model_name": "ollama/llama3.1:8b",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maps_rows_to_items() -> None:
    row = _row()
    svc = _service([row])
    items = await svc.list_recent(limit=6, offset=0)

    assert len(items) == 1
    item = items[0]
    assert item.id == row["id"]
    assert item.query == row["query_text"]
    assert item.status == "completed"
    assert item.latency_ms == 312
    assert item.grounding_score == pytest.approx(0.94)
    assert item.model == "ollama/llama3.1:8b"
    repo = cast(FakeRepo, svc.queries)
    assert repo.args == {"limit": 6, "offset": 0}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_null_grounding_and_model_pass_through_as_none() -> None:
    # An abstained / failed session with no generated_answer joined.
    svc = _service([_row(status="abstained", grounding_score=None, model_name=None, latency_ms=None)])
    items = await svc.list_recent()
    assert items[0].status == "abstained"
    assert items[0].grounding_score is None
    assert items[0].model is None
    assert items[0].latency_ms is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decimal_grounding_is_coerced_to_float() -> None:
    svc = _service([_row(grounding_score=Decimal("0.872"))])
    items = await svc.list_recent()
    assert isinstance(items[0].grounding_score, float)
    assert items[0].grounding_score == pytest.approx(0.872)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_history_returns_empty_list() -> None:
    svc = _service([])
    assert await svc.list_recent() == []
