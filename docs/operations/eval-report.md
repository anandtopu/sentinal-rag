# Eval comparison report — placeholder

This file is overwritten by `tests/performance/evals/compare.py` on every
run. Until a deployed dev environment + a seeded eval dataset are
available (Phase 7 Slice 3 deliverables: cluster bootstrap charts +
GHCR image push pipeline), this placeholder records the **shape** the
report will take.

## Planned comparisons

The harness ships three comparison configurations:

1. **`hybrid-vs-vector`** — does combining BM25 + pgvector via Reciprocal
   Rank Fusion beat vector-only retrieval? Expectation per ADR-0004:
   yes on multi-term queries, marginal or worse on pure semantic
   queries.
2. **`rerank-vs-no`** — does the bge-reranker-v2-m3 cross-encoder pass
   improve answer quality enough to justify its 3–10s warm-up cost?
   Expectation per ADR-0006: yes, especially on `CitationAccuracy` and
   `Faithfulness`, with a small `ContextRelevance` lift.
3. **`prompt-v2-vs-v1`** — does a tightened prompt template (with
   stricter abstain instructions, explicit citation format) improve
   `Faithfulness` and reduce hallucination risk? Expectation:
   incremental but measurable; `AnswerCorrectness` may be flat or down
   slightly because the prompt is more conservative.

## Expected report shape (per comparison)

```
| Evaluator              | Before mean | After mean | Δ      | Improved | Regressed | Tied |
|------------------------|------------:|-----------:|-------:|---------:|----------:|-----:|
| context_relevance      |       0.47  |      0.59  | +0.12  |       28 |         5 |    7 |
| faithfulness           |       0.71  |      0.83  | +0.12  |       31 |         3 |    6 |
| answer_correctness     |       0.62  |      0.66  | +0.04  |       21 |         9 |   10 |
| citation_accuracy_f1   |       0.55  |      0.71  | +0.16  |       26 |         4 |   10 |
```

(Numbers above are illustrative — replaced by real ones once the
harness has been run against a deployed environment.)

## Running

See [`tests/performance/evals/README.md`](../../tests/performance/evals/README.md)
for the CLI invocation. The harness writes its output here, replacing
this placeholder.

## Methodology (reproducibility)

- Each case is sent twice: once with the comparison's *before*
  retrieval/prompt overrides, once with the *after* overrides. All
  other knobs (model, temperature, top-k for the unchanged stages,
  collection scope, prompt version) are held constant.
- Scoring uses the four custom evaluators in
  `sentinelrag_shared.evaluation` (`ContextRelevance`, `Faithfulness`,
  `AnswerCorrectness`, `CitationAccuracy`). These are
  token-overlap-based — fast, deterministic, no LLM-judge cost.
- ragas-backed scoring is the planned Phase 9 follow-up; it adds an
  `LLMAsJudgeAccuracy` column at meaningful per-case dollar cost.
- Failed requests are listed but excluded from the mean. A flaked
  comparison is re-run rather than partial-mean'd.

## Cross-references

- [ADR-0004](../architecture/adr/0004-postgres-fts-over-opensearch.md) — Postgres FTS (justifies the hybrid comparison)
- [ADR-0006](../architecture/adr/0006-bge-reranker.md) — bge-reranker (justifies the rerank comparison)
- [ADR-0019](../architecture/adr/0019-evaluation-framework-ragas.md) — ragas + custom evaluator strategy
- [ADR-0029](../architecture/adr/0029-portfolio-polish.md) — why this report ships as a harness-with-placeholder rather than as static numbers
