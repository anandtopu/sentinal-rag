"""Unit tests for EvaluationService.summaries_for (ADR-0040).

Covers the batch summary shaping — per-run mapping, cases_total = completed +
failed, and the empty summary for runs with no scored cases — with a
duck-typed fake score repository (no Postgres).
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from app.services.evaluation_service import EvaluationService
from sqlalchemy.ext.asyncio import AsyncSession


class FakeScoresRepo:
    def __init__(self, aggs: dict[Any, dict[str, Any]]) -> None:
        self._aggs = aggs
        self.called_with: list[Any] | None = None

    async def aggregate_for_runs(self, run_ids: list[Any]) -> dict[Any, dict[str, Any]]:
        self.called_with = run_ids
        return {k: v for k, v in self._aggs.items() if k in run_ids}


def _service(aggs: dict[Any, dict[str, Any]]) -> EvaluationService:
    svc = EvaluationService(db=cast(AsyncSession, object()))
    svc.scores = cast(Any, FakeScoresRepo(aggs))
    return svc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summaries_for_builds_per_run_summaries() -> None:
    r1, r2 = uuid4(), uuid4()
    aggs = {
        r1: {
            "context_relevance_avg": 0.74,
            "faithfulness_avg": 0.91,
            "answer_correctness_avg": 0.87,
            "citation_accuracy_avg": 0.96,
            "average_latency_ms": 312,
            "total_cost_usd": 0.0041,
            "cases_completed": 9,
            "cases_failed": 1,
        },
    }
    svc = _service(aggs)
    out = await svc.summaries_for([r1, r2])

    assert set(out) == {r1, r2}
    # r1 — populated from the aggregate
    assert out[r1].faithfulness_avg == 0.91
    assert out[r1].citation_accuracy_avg == 0.96
    assert out[r1].average_latency_ms == 312
    assert out[r1].cases_completed == 9
    assert out[r1].cases_failed == 1
    assert out[r1].cases_total == 10  # completed + failed
    # r2 — no scored cases → empty summary
    assert out[r2].faithfulness_avg is None
    assert out[r2].cases_total == 0
    assert out[r2].cases_completed == 0
    # the batch was queried with every requested run id
    assert cast(FakeScoresRepo, svc.scores).called_with == [r1, r2]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summaries_for_empty_run_list() -> None:
    svc = _service({})
    assert await svc.summaries_for([]) == {}
