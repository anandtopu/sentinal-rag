# Eval comparison harness

`compare.py` produces a before/after delta report for one of three
SentinelRAG retrieval/prompt design choices, against a deployed API.

| Comparison | What it measures |
|---|---|
| `hybrid-vs-vector` | Hybrid retrieval (BM25 + vector + RRF) vs vector-only |
| `rerank-vs-no` | bge-reranker-v2-m3 vs NoOpReranker |
| `prompt-v2-vs-v1` | A specific prompt version vs another (UUIDs via CLI flags) |

Each case is sent to `POST /api/v1/query` twice — once with the
"before" overrides, once with "after" — and the four custom evaluators
in `sentinelrag_shared.evaluation` (`ContextRelevance`,
`Faithfulness`, `AnswerCorrectness`, `CitationAccuracy`) score both
sides. The report aggregates means + per-case improved/regressed/tied
counts.

## Run

```bash
uv run python tests/performance/evals/compare.py \
    --base-url       https://api.dev.sentinelrag.example.com \
    --token          "$BEARER" \
    --collection-ids <uuid> <uuid> \
    --compare        hybrid-vs-vector \
    --output         docs/operations/eval-report.md
```

For `prompt-v2-vs-v1`, also pass `--before-prompt-id` / `--after-prompt-id`
with prompt-version UUIDs.

The default fixture under `fixtures/dataset.json` is a 3-case smoke set
so the harness can run end-to-end against the local stack without a
seeded eval dataset. Real eval datasets live in the `eval_datasets` /
`eval_cases` Postgres tables and are wired to the harness via the
`EvaluationService` runner (Phase 9 follow-up).

## Output

Generates a markdown report at `--output` with:

- Per-evaluator before / after / Δ table
- Per-evaluator improved / regressed / tied counts
- A list of failed requests (network errors, etc.)
- A "Methodology" footer naming the comparison config used

The committed report at `docs/operations/eval-report.md` is the
operator's interpretation; this script overwrites it on each run.
