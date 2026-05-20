"""Evaluation repositories."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
    EvaluationScore,
)
from app.db.repositories.base import BaseRepository


class EvaluationDatasetRepository(BaseRepository[EvaluationDataset]):
    model = EvaluationDataset

    async def get_by_name(self, name: str) -> EvaluationDataset | None:
        stmt = select(EvaluationDataset).where(EvaluationDataset.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[EvaluationDataset]:
        stmt = (
            select(EvaluationDataset)
            .order_by(EvaluationDataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class EvaluationCaseRepository(BaseRepository[EvaluationCase]):
    model = EvaluationCase

    async def list_for_dataset(self, dataset_id: UUID) -> list[EvaluationCase]:
        stmt = (
            select(EvaluationCase)
            .where(EvaluationCase.dataset_id == dataset_id)
            .order_by(EvaluationCase.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_dataset(self, dataset_id: UUID) -> int:
        stmt = select(func.count(EvaluationCase.id)).where(
            EvaluationCase.dataset_id == dataset_id
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class EvaluationRunRepository(BaseRepository[EvaluationRun]):
    model = EvaluationRun

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[EvaluationRun]:
        stmt = (
            select(EvaluationRun)
            .order_by(EvaluationRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class EvaluationScoreRepository(BaseRepository[EvaluationScore]):
    model = EvaluationScore

    async def list_for_run(self, run_id: UUID) -> list[EvaluationScore]:
        stmt = select(EvaluationScore).where(
            EvaluationScore.evaluation_run_id == run_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def aggregate_for_run(self, run_id: UUID) -> dict[str, float | None]:
        stmt = select(
            func.avg(EvaluationScore.context_relevance_score)
            .filter(EvaluationScore.status == "completed")
            .label("ctx"),
            func.avg(EvaluationScore.faithfulness_score)
            .filter(EvaluationScore.status == "completed")
            .label("faith"),
            func.avg(EvaluationScore.answer_correctness_score)
            .filter(EvaluationScore.status == "completed")
            .label("ans"),
            func.avg(EvaluationScore.citation_accuracy_score)
            .filter(EvaluationScore.status == "completed")
            .label("cite"),
            func.avg(EvaluationScore.latency_ms)
            .filter(EvaluationScore.status == "completed")
            .label("lat"),
            func.sum(EvaluationScore.cost_usd)
            .filter(EvaluationScore.status == "completed")
            .label("cost"),
            func.count(EvaluationScore.id)
            .filter(EvaluationScore.status == "completed")
            .label("completed"),
            func.count(EvaluationScore.id)
            .filter(EvaluationScore.status == "failed")
            .label("failed"),
        ).where(EvaluationScore.evaluation_run_id == run_id)
        result = await self.session.execute(stmt)
        row = result.one()
        return {
            "context_relevance_avg": float(row.ctx) if row.ctx is not None else None,
            "faithfulness_avg": float(row.faith) if row.faith is not None else None,
            "answer_correctness_avg": float(row.ans) if row.ans is not None else None,
            "citation_accuracy_avg": float(row.cite) if row.cite is not None else None,
            "average_latency_ms": int(row.lat) if row.lat is not None else None,
            "total_cost_usd": float(row.cost) if row.cost is not None else None,
            "cases_completed": int(row.completed),
            "cases_failed": int(row.failed),
        }

    async def aggregate_for_runs(
        self, run_ids: list[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        """Aggregate scores for many runs in one ``GROUP BY`` query (ADR-0040).

        Returns a map ``run_id -> agg``; runs with no scored cases are absent
        from the map (the caller treats them as empty summaries).
        """
        if not run_ids:
            return {}
        completed = EvaluationScore.status == "completed"
        stmt = (
            select(
                EvaluationScore.evaluation_run_id.label("run_id"),
                func.avg(EvaluationScore.context_relevance_score).filter(completed).label("ctx"),
                func.avg(EvaluationScore.faithfulness_score).filter(completed).label("faith"),
                func.avg(EvaluationScore.answer_correctness_score).filter(completed).label("ans"),
                func.avg(EvaluationScore.citation_accuracy_score).filter(completed).label("cite"),
                func.avg(EvaluationScore.latency_ms).filter(completed).label("lat"),
                func.sum(EvaluationScore.cost_usd).filter(completed).label("cost"),
                func.count(EvaluationScore.id).filter(completed).label("completed"),
                func.count(EvaluationScore.id)
                .filter(EvaluationScore.status == "failed")
                .label("failed"),
            )
            .where(EvaluationScore.evaluation_run_id.in_(run_ids))
            .group_by(EvaluationScore.evaluation_run_id)
        )
        result = await self.session.execute(stmt)
        out: dict[UUID, dict[str, Any]] = {}
        for row in result.all():
            out[row.run_id] = {
                "context_relevance_avg": float(row.ctx) if row.ctx is not None else None,
                "faithfulness_avg": float(row.faith) if row.faith is not None else None,
                "answer_correctness_avg": float(row.ans) if row.ans is not None else None,
                "citation_accuracy_avg": float(row.cite) if row.cite is not None else None,
                "average_latency_ms": int(row.lat) if row.lat is not None else None,
                "total_cost_usd": float(row.cost) if row.cost is not None else None,
                "cases_completed": int(row.completed),
                "cases_failed": int(row.failed),
            }
        return out
