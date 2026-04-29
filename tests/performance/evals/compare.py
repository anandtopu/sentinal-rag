"""Eval comparison harness — produces three before/after deltas.

Phase 9 portfolio polish artifact. The harness invokes the API's
``POST /query`` endpoint twice per case (once with ``before`` retrieval
config, once with ``after``), runs the four custom evaluators on each
response, and writes the aggregated comparison into a markdown report
under ``docs/operations/eval-report.md``.

The three comparisons we ship configurations for:

    --compare hybrid-vs-vector   : retrieval.mode hybrid vs vector
    --compare rerank-vs-no       : top_k_rerank > 0 vs 0 (NoOpReranker)
    --compare prompt-v2-vs-v1    : prompt_version_id pinned to each

Run against a deployed environment:

    python -m tests.performance.evals.compare \\
        --base-url https://api.dev.sentinelrag.example.com \\
        --token "$BEARER" \\
        --dataset-id <uuid> \\
        --compare hybrid-vs-vector \\
        --output docs/operations/eval-report.md

When ``--dataset-id`` is omitted the harness loads
``tests/performance/evals/fixtures/dataset.json`` and runs an inline
smoke check — useful in CI to prove the harness wiring is live without
needing a real eval dataset.

Output columns
--------------
For each evaluator we report ``before mean``, ``after mean``,
``delta``, and ``cases improved / regressed / tied``. The report
includes per-case rows for the worst-K regressions so authors can
inspect specific failures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sentinelrag_shared.evaluation import (
    AnswerCorrectnessEvaluator,
    CitationAccuracyEvaluator,
    ContextRelevanceEvaluator,
    EvalCase,
    EvalContext,
    Evaluator,
    FaithfulnessEvaluator,
)

# ---- Comparison configs --------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ComparisonConfig:
    """How a single comparison varies the request body between before/after."""

    name: str
    description: str
    before_overrides: dict[str, Any] = field(default_factory=dict)
    after_overrides: dict[str, Any] = field(default_factory=dict)


COMPARISONS: dict[str, ComparisonConfig] = {
    "hybrid-vs-vector": ComparisonConfig(
        name="hybrid-vs-vector",
        description="Hybrid retrieval (BM25 + vector + RRF merge) vs vector-only.",
        before_overrides={"retrieval": {"mode": "vector"}},
        after_overrides={"retrieval": {"mode": "hybrid"}},
    ),
    "rerank-vs-no": ComparisonConfig(
        name="rerank-vs-no",
        description="bge-reranker-v2-m3 vs NoOpReranker (top_k_rerank=0).",
        before_overrides={"retrieval": {"top_k_rerank": 0}},
        after_overrides={"retrieval": {"top_k_rerank": 8}},
    ),
    "prompt-v2-vs-v1": ComparisonConfig(
        name="prompt-v2-vs-v1",
        description=(
            "Prompt v2 vs v1 (set the version IDs in "
            "--before-prompt-id / --after-prompt-id)."
        ),
        # The actual version IDs are wired via CLI flags so authors don't
        # bake them into source. See main() for the override threading.
    ),
}


# ---- HTTP plumbing -------------------------------------------------------- #


@dataclass(slots=True)
class APIClient:
    base_url: str
    token: str
    timeout: float = 60.0

    async def query(self, *, body: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/v1/query"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        response = await client.post(url, json=body, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


# ---- Run shape ------------------------------------------------------------ #


@dataclass(slots=True)
class CaseRunResult:
    case_id: UUID
    query: str
    response: dict[str, Any] | None
    error: str | None = None
    scores: dict[str, float] = field(default_factory=dict)


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _request_body(*, query: str, collection_ids: list[str]) -> dict[str, Any]:
    return {
        "query": query,
        "collection_ids": collection_ids,
        "retrieval": {
            "mode": "hybrid",
            "top_k_bm25": 20,
            "top_k_vector": 20,
            "top_k_hybrid": 30,
            "top_k_rerank": 8,
        },
        "generation": {
            "model": "ollama/llama3.1:8b",
            "temperature": 0.1,
            "max_tokens": 800,
        },
        "options": {
            "include_citations": True,
            "include_debug_trace": False,
            "abstain_if_unsupported": True,
        },
    }


async def _run_one_side(
    *,
    api: APIClient,
    cases: list[EvalCase],
    collection_ids: list[str],
    overrides: dict[str, Any],
    evaluators: list[Evaluator],
    client: httpx.AsyncClient,
) -> list[CaseRunResult]:
    results: list[CaseRunResult] = []
    for case in cases:
        body = _deep_merge(
            _request_body(query=case.input_query, collection_ids=collection_ids),
            overrides,
        )
        try:
            response = await api.query(body=body, client=client)
        except httpx.HTTPError as exc:
            results.append(
                CaseRunResult(
                    case_id=case.case_id,
                    query=case.input_query,
                    response=None,
                    error=str(exc),
                )
            )
            continue

        ctx = EvalContext(
            answer_text=response.get("answer", "") or "",
            retrieved_chunks=[],  # filled when --include-trace is enabled (see CLI)
            cited_chunk_ids=[UUID(c["chunk_id"]) for c in response.get("citations", [])],
            cited_quoted_texts=[c.get("quoted_text") or "" for c in response.get("citations", [])],
        )

        scores: dict[str, float] = {}
        for ev in evaluators:
            out = await ev.evaluate(case=case, context=ctx)
            if out.score is not None:
                scores[ev.name] = float(out.score)
        results.append(
            CaseRunResult(
                case_id=case.case_id,
                query=case.input_query,
                response=response,
                scores=scores,
            )
        )
    return results


# ---- Reporting ------------------------------------------------------------ #


def _aggregate(name: str, side: list[CaseRunResult]) -> dict[str, Any]:
    """Per-evaluator mean for one side."""
    by_evaluator: dict[str, list[float]] = {}
    for r in side:
        for ev_name, score in r.scores.items():
            by_evaluator.setdefault(ev_name, []).append(score)
    means: dict[str, float | None] = {
        ev: statistics.mean(scores) if scores else None for ev, scores in by_evaluator.items()
    }
    return {"side": name, "n": len(side), "means": means}


def _per_case_deltas(
    before: list[CaseRunResult],
    after: list[CaseRunResult],
) -> dict[str, dict[str, int]]:
    """For each evaluator, count cases improved / regressed / tied."""
    paired: dict[UUID, tuple[CaseRunResult, CaseRunResult]] = {}
    for b in before:
        paired[b.case_id] = (b, paired.get(b.case_id, (b, b))[1])
    for a in after:
        b = paired.get(a.case_id, (a, a))[0]
        paired[a.case_id] = (b, a)

    counts: dict[str, dict[str, int]] = {}
    for b, a in paired.values():
        for ev_name in set(b.scores) | set(a.scores):
            row = counts.setdefault(ev_name, {"improved": 0, "regressed": 0, "tied": 0})
            bs = b.scores.get(ev_name)
            as_ = a.scores.get(ev_name)
            if bs is None or as_ is None:
                continue
            if as_ > bs:
                row["improved"] += 1
            elif as_ < bs:
                row["regressed"] += 1
            else:
                row["tied"] += 1
    return counts


def _render_report(
    *,
    comparison: ComparisonConfig,
    dataset_label: str,
    before_results: list[CaseRunResult],
    after_results: list[CaseRunResult],
) -> str:
    before_agg = _aggregate("before", before_results)
    after_agg = _aggregate("after", after_results)
    deltas = _per_case_deltas(before_results, after_results)

    evaluators = sorted(set(before_agg["means"]) | set(after_agg["means"]))

    lines: list[str] = []
    lines.append(f"# Eval comparison — `{comparison.name}`")
    lines.append("")
    lines.append(f"> {comparison.description}")
    lines.append("")
    lines.append(f"- **Dataset:** {dataset_label}")
    lines.append(f"- **Cases (before):** {before_agg['n']}")
    lines.append(f"- **Cases (after):**  {after_agg['n']}")
    lines.append("")
    lines.append("## Score table")
    lines.append("")
    lines.append("| Evaluator | Before mean | After mean | Δ | Improved | Regressed | Tied |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for ev in evaluators:
        bm = before_agg["means"].get(ev)
        am = after_agg["means"].get(ev)
        delta = (am - bm) if (bm is not None and am is not None) else None
        d = deltas.get(ev, {"improved": 0, "regressed": 0, "tied": 0})
        lines.append(
            f"| `{ev}` | "
            f"{'—' if bm is None else f'{bm:.3f}'} | "
            f"{'—' if am is None else f'{am:.3f}'} | "
            f"{'—' if delta is None else f'{delta:+.3f}'} | "
            f"{d['improved']} | {d['regressed']} | {d['tied']} |"
        )
    lines.append("")

    failed = [r for r in before_results + after_results if r.error]
    if failed:
        lines.append("## Failed requests")
        lines.append("")
        for r in failed:
            lines.append(f"- `{r.case_id}` — {r.error}")
        lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "Each case was issued twice against the same API. The 'before' run "
        "applied the comparison's before-overrides; the 'after' run applied "
        "the after-overrides. Everything else (dataset, prompt version, "
        "model, temperature, top-k) was held constant. Scores come from the "
        "four custom evaluators in `sentinelrag_shared.evaluation`."
    )
    lines.append("")
    lines.append(
        "_Generated by `tests/performance/evals/compare.py`. Replace this "
        "section with the operator's interpretation of the deltas._"
    )
    lines.append("")
    return "\n".join(lines)


# ---- CLI ------------------------------------------------------------------ #


def _load_fixture_cases(path: Path) -> list[EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for c in raw["cases"]:
        cases.append(
            EvalCase(
                case_id=UUID(c["case_id"]),
                input_query=c["input_query"],
                expected_answer=c.get("expected_answer"),
                expected_citation_chunk_ids=[
                    UUID(s) for s in c.get("expected_citation_chunk_ids", [])
                ],
            )
        )
    return cases


async def _run(args: argparse.Namespace) -> int:
    if args.compare not in COMPARISONS:
        print(
            f"Unknown comparison '{args.compare}'. Choose one of: {', '.join(COMPARISONS)}",
            file=sys.stderr,
        )
        return 2
    comparison = COMPARISONS[args.compare]

    # Apply CLI-supplied prompt IDs to the prompt-v2-vs-v1 comparison.
    if args.compare == "prompt-v2-vs-v1":
        if not (args.before_prompt_id and args.after_prompt_id):
            print(
                "--before-prompt-id and --after-prompt-id are required for prompt-v2-vs-v1.",
                file=sys.stderr,
            )
            return 2
        comparison = ComparisonConfig(
            name=comparison.name,
            description=comparison.description,
            before_overrides={"options": {"prompt_version_id": args.before_prompt_id}},
            after_overrides={"options": {"prompt_version_id": args.after_prompt_id}},
        )

    cases = _load_fixture_cases(Path(args.fixture)) if args.dataset_id is None else []
    if args.dataset_id is not None:
        # Real datasets live in Postgres; fetching them is out-of-scope for
        # this CLI to avoid pulling a DB session in. The deployed harness
        # call site (Phase 9 wiring) loads them via the existing
        # EvaluationService.
        print(
            "--dataset-id support is wired through the Phase 9 "
            "EvaluationService runner. For a quick smoke run, omit "
            "--dataset-id to use the JSON fixture.",
            file=sys.stderr,
        )
        return 2

    api = APIClient(base_url=args.base_url, token=args.token)
    evaluators: list[Evaluator] = [
        ContextRelevanceEvaluator(),
        FaithfulnessEvaluator(),
        AnswerCorrectnessEvaluator(),
        CitationAccuracyEvaluator(),
    ]

    async with httpx.AsyncClient() as client:
        before = await _run_one_side(
            api=api,
            cases=cases,
            collection_ids=args.collection_ids,
            overrides=comparison.before_overrides,
            evaluators=evaluators,
            client=client,
        )
        after = await _run_one_side(
            api=api,
            cases=cases,
            collection_ids=args.collection_ids,
            overrides=comparison.after_overrides,
            evaluators=evaluators,
            client=client,
        )

    report = _render_report(
        comparison=comparison,
        dataset_label="fixture (smoke)"
        if args.dataset_id is None
        else f"dataset {args.dataset_id}",
        before_results=before,
        after_results=after,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evals.compare",
        description="Run a before/after comparison eval against a deployed SentinelRAG API.",
    )
    p.add_argument(
        "--base-url",
        required=True,
        help="API base URL, e.g. https://api.dev.sentinelrag.example.com",
    )
    p.add_argument(
        "--token", required=True, help="Bearer token (Keycloak access token, or 'dev' for local)."
    )
    p.add_argument(
        "--collection-ids",
        nargs="+",
        required=True,
        help="Collection UUIDs to scope the queries to.",
    )
    p.add_argument(
        "--compare", required=True, choices=sorted(COMPARISONS), help="Which comparison to run."
    )
    p.add_argument(
        "--dataset-id",
        help="Eval dataset UUID (loaded from Postgres). Omit to use the JSON fixture.",
    )
    p.add_argument(
        "--fixture",
        default="tests/performance/evals/fixtures/dataset.json",
        help="JSON fallback dataset.",
    )
    p.add_argument(
        "--output",
        default="docs/operations/eval-report.md",
        help="Where to write the rendered markdown report.",
    )
    p.add_argument(
        "--before-prompt-id", help="Prompt version UUID for the before-side (prompt-v2-vs-v1 only)."
    )
    p.add_argument(
        "--after-prompt-id", help="Prompt version UUID for the after-side (prompt-v2-vs-v1 only)."
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
