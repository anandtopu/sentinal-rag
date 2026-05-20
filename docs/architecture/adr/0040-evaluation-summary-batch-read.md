# ADR-0040: Evaluation run summaries — live aggregation + batch read, not denormalized

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** architect, solo maintainer
- **Tags:** api, evaluation, read-model, performance

## Context

[BACKLOG.md](../BACKLOG.md) **B10 item #4** was framed as: "runs don't yet
persist per-metric averages reliably, so the evaluations leaderboard /
medians / trend read `—`. Ensure the evaluation workflow writes
`faithfulness_avg` … on run completion."

Investigating the actual code changed the picture:

- `GET /api/v1/eval/runs/{id}` **already returns real per-metric averages.**
  `EvaluationService.aggregate_run` calls
  `EvaluationScoreRepository.aggregate_for_run`, which `AVG()`s the four
  metric columns (`context_relevance_score`, `faithfulness_score`,
  `answer_correctness_score`, `citation_accuracy_score`) over the per-case
  `evaluation_scores` rows, filtered to `status='completed'`, plus latency /
  cost / case counts. The per-case rows are written by the Temporal
  evaluation worker (`activities/evaluation.py`). So the summary is computed
  **live** and is correct whenever a run has scored cases.
- The `—` the frontend shows is therefore **not** a missing-data bug in the
  real backend. It comes from two places: (a) in the mocked e2e/demo,
  `GET /eval/runs/{id}` isn't mocked; (b) the evaluations page fans out **one
  `getEvalRun` call per run** (`useQueries`), each of which 404s for any run
  without scores — an N+1 with N failure points.

So the real defect is the **read shape** (N+1 fan-out), not missing
persistence. The question is whether to (a) denormalize a summary snapshot
onto `evaluation_runs` and have the worker write it on completion (the
literal B10 #4 wording), or (b) keep live aggregation and batch the read.

## Decision

Keep evaluation summaries **computed live** from `evaluation_scores`
(per-case rows stay the single source of truth). Add a **batch read**:
`GET /api/v1/eval/runs?include=summary` returns each run with its summary
attached, aggregated server-side in **one** grouped query. The frontend
evaluations page makes a single call instead of N.

Do **not** denormalize a summary snapshot onto `evaluation_runs`, and do
**not** add a worker aggregation step.

### Shape

- `EvaluationRunRead` gains an optional `summary: EvaluationScoreSummary |
  null` (default `null`) — additive, so existing consumers (the dashboard's
  run count, `latestRunId`) are unaffected.
- `GET /eval/runs?include=summary` populates `summary` on each row.
  `EvaluationScoreRepository.aggregate_for_runs(run_ids)` runs **one**
  `GROUP BY evaluation_run_id` over `evaluation_scores`, so the cost is one
  query regardless of run count (vs. N).
- In the batch path `cases_total` is reported as `completed + failed` (the
  scored cases). For a *completed* run that equals the dataset's case count;
  the exact dataset-case count remains available on the per-run
  `GET /eval/runs/{id}` (which keeps `count_for_dataset`). Documented
  approximation, not a silent one.
- `GET /eval/runs/{id}` is unchanged — still live-aggregates with exact
  `cases_total`.

### Why not denormalize a snapshot onto the run row

- **Drift.** A denormalized `*_avg` on `evaluation_runs` can disagree with
  the per-case rows it's derived from. Live aggregation can't drift.
- **Premature.** The motivating problem (frontend `—`) is the N+1, which the
  batch read solves directly. Denormalization solves a problem we don't have
  (read cost is already trivial at demo scale; the batch makes it one query).
- **RTBF.** [ADR-0032](0032-right-to-be-forgotten.md) purges *document /
  content* data, not evaluation scores, so "snapshot survives a purge of the
  per-case rows" isn't a live requirement.
- **Cost.** Denormalization needs a schema migration (8 columns), ORM
  changes, a worker aggregation activity + workflow wiring, and a read path
  that prefers snapshot-then-falls-back — all to cache a cheap aggregate. Not
  worth it now.

If a future requirement *does* need a durable snapshot (e.g. evaluation
scores become subject to retention purges, or runs reach a scale where the
grouped aggregate is slow), revisit with an expand→backfill→contract
migration per [ADR-0033](0033-zero-downtime-schema-migrations.md). This ADR
records *why* the snapshot was deliberately not built, so it isn't re-added
on a misreading of B10 #4.

## Consequences

### Positive

- The evaluations leaderboard / medians / trend load in **one** request with
  real, live-aggregated numbers; no N+1, no per-run 404 fragility.
- No migration, no new write path, no worker change, no denormalization to
  keep consistent. Per-case rows stay the single source of truth.
- `EvaluationRunRead.summary` is additive and opt-in via `include=summary`.

### Negative

- Batch `cases_total` is the scored-case count (`completed + failed`), which
  for a not-yet-finished run undercounts the dataset. Acceptable: the
  leaderboard cares about scored runs, and the exact count is one
  `GET /eval/runs/{id}` away.
- Summaries are recomputed per request (not cached). At demo scale a single
  grouped aggregate is cheap; if it ever isn't, the snapshot path above is
  the documented next step.

### Neutral

- `include` is a comma-friendly string param (`?include=summary`) so more
  includable expansions can be added later without a new param.

## Alternatives considered

### Option A — Live aggregation + batch read (this)
See above. Solves the real problem (N+1) with no schema change.

### Option B — Denormalize summary onto `evaluation_runs`, worker writes on completion
The literal B10 #4 wording.
- **Pros:** O(1) run-row read; snapshot survives per-case row deletion.
- **Cons:** Drift risk; migration + ORM + worker activity + workflow wiring +
  read-preference branch; caches an aggregate that's already cheap.
- **Rejected because:** premature optimization against a problem we don't
  have; the batch read delivers the user-visible win without the denormalized
  state to keep consistent. Revisit only with a concrete durability/scale
  driver.

### Option C — Leave the N+1 fan-out, just mock `getEvalRun`
- **Pros:** Zero backend change; the live per-run endpoint already works.
- **Cons:** Keeps N requests + N 404 points on the real page; only "fixes"
  the demo via a mock.
- **Rejected because:** it papers over the real fragility instead of removing
  it.

## Notes on the design docs

Refines [BACKLOG.md](../BACKLOG.md) B10 #4: the per-run summary was already
served live (not missing), so #4 is closed by batching the read rather than
by persisting a snapshot. No PRD/Architecture override.

## References

- [ADR-0038](0038-metrics-summary-read-model.md),
  [ADR-0039](0039-usage-cost-summary-read-model.md) — sibling read-models
  (Postgres-aggregate, RLS-scoped) this follows
- [ADR-0019](0019-evaluation-framework-ragas.md) — the evaluators whose
  per-case scores are aggregated
- [ADR-0032](0032-right-to-be-forgotten.md),
  [ADR-0033](0033-zero-downtime-schema-migrations.md) — referenced in the
  "why not denormalize" rationale
- `apps/api/app/db/repositories/evaluations.py` (`aggregate_for_run`),
  `apps/temporal-worker/sentinelrag_worker/activities/evaluation.py`
  (per-case score writes)
