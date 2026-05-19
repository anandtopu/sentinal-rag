# Runbook — retrieval-transport benchmark (R4.S6 / ADR-0031)

> **Audience:** Operator with `kubectl` access to a SentinelRAG dev/staging
> cluster, the k6 CLI installed locally, and `uv` available for the
> Python harness.

[ADR-0031](../../architecture/adr/0031-retrieval-service-extraction.md)
ships the HTTP retrieval transport behind a Helm-configurable switch
but keeps the **default in-process** until this benchmark proves the
HTTP path's p95 is inside the SLO budget. This runbook is the procedure
that produces the benchmark report and feeds the data into the ADR's
"Benchmark" section.

Per [ADR-0029](../../architecture/adr/0029-portfolio-polish.md), no
hand-edited numbers go into the report. The harnesses below generate
the markdown.

## Prerequisites

- Cluster running the SentinelRAG Helm chart at a release pinned to a
  commit that includes R4.S6's harness wiring.
- A demo tenant + at least one populated collection. `make seed`
  against the cluster works; alternatively use the per-tenant data
  the dev cluster already carries.
- `k6` ≥ v0.50 on the operator's machine (`brew install k6` or scoop).
- A bearer token that can be used in the `Authorization` header against
  both API deployments. For dev clusters, `Bearer dev` works as long as
  `AUTH_ALLOW_DEV_TOKEN=true` + `ENVIRONMENT=local` are set in the API
  pod's ConfigMap (NOT the case for staging/prod).
- ~30 minutes wall-clock per transport (10-minute steady RPS phase + 5
  minutes of build/teardown).

## Step 1 — Stand up two API deployments, differing only in transport

The chart's default `values.yaml` sets `RETRIEVAL_TRANSPORT=http`. For
the comparison we need **both** transports live concurrently against
the *same* underlying data so quality scores are comparable.

Option A — two separate Helm releases in two namespaces:

```bash
# Release A: in-process transport.
helm upgrade --install sentinelrag-inprocess infra/helm/sentinelrag \
  --namespace sentinelrag-benchmark-inprocess --create-namespace \
  -f infra/helm/sentinelrag/values-dev.yaml \
  --set api.envFromConfigMap.RETRIEVAL_TRANSPORT=in-process \
  --set retrieval.enabled=false

# Release B: HTTP transport (default).
helm upgrade --install sentinelrag-http infra/helm/sentinelrag \
  --namespace sentinelrag-benchmark-http --create-namespace \
  -f infra/helm/sentinelrag/values-dev.yaml
```

Both releases point at the same Postgres (set `DATABASE_URL` via
ExternalSecret to the same DSN in both namespaces) so retrieval sees
identical chunks.

Option B — single Helm release, re-deploy between runs. Faster on a
small cluster; gives up the side-by-side latency property if the LLM
provider's tail latency drifts between runs.

The remainder of this runbook assumes Option A; substitute single-URL
form for Option B as needed.

## Step 2 — Latency benchmark via k6 (`transport-compare.js`)

Run twice, once per transport, with the matching `TRANSPORT_LABEL`:

```bash
# In-process.
SENTINELRAG_BASE_URL=https://api.sentinelrag-benchmark-inprocess.dev.example.com \
SENTINELRAG_AUTH_TOKEN="$BEARER" \
SENTINELRAG_COLLECTION_IDS="$DEMO_COLLECTION_UUID" \
SENTINELRAG_TRANSPORT_LABEL=in-process \
  k6 run \
    --out json=in-process.json \
    --summary-export=in-process-summary.json \
    tests/performance/k6/transport-compare.js

# HTTP.
SENTINELRAG_BASE_URL=https://api.sentinelrag-benchmark-http.dev.example.com \
SENTINELRAG_AUTH_TOKEN="$BEARER" \
SENTINELRAG_COLLECTION_IDS="$DEMO_COLLECTION_UUID" \
SENTINELRAG_TRANSPORT_LABEL=http \
  k6 run \
    --out json=http.json \
    --summary-export=http-summary.json \
    tests/performance/k6/transport-compare.js
```

What to verify after each run:

- `http_req_failed{name:POST /query}` threshold passed → no error
  regression.
- `rag_query_latency_ms` p95 and p99 thresholds passed → SLO honored.
- The k6 console shows `rag_query_abstain` near zero (abstention
  shouldn't fluctuate between transports; if it does, the demo
  collection isn't covering the test queries cleanly — fix the seed
  before publishing the report).

## Step 3 — Quality comparison via `compare.py`

The quality side checks that the two transports return semantically
equivalent answers. They should — the retrieval logic is identical;
the only thing that changes is whether the call is in-process or over
httpx — but a divergence here would surface a real bug (auth context
loss, RLS bypass on the network hop, etc.).

```bash
uv run python tests/performance/evals/compare.py \
  --compare retrieval-transport \
  --before-base-url https://api.sentinelrag-benchmark-inprocess.dev.example.com \
  --after-base-url  https://api.sentinelrag-benchmark-http.dev.example.com \
  --token "$BEARER" \
  --collection-ids "$DEMO_COLLECTION_UUID" \
  --output docs/operations/eval-report.md
```

Open the rendered `docs/operations/eval-report.md` and read the score
table. The four custom evaluators (`context_relevance`,
`faithfulness`, `answer_correctness`, `citation_accuracy`) should each
show Δ within ±0.02. A larger delta is a red flag — investigate
before flipping the default transport.

## Step 4 — Summarize the latency JSONs

`compare.py` writes the eval table; the latency numbers come from
the two k6 summary JSONs. Use the in-repo summarizer:

```bash
uv run python tests/performance/k6/summarize_transport.py \
  --inprocess in-process-summary.json \
  --http http-summary.json \
  --output docs/operations/retrieval-benchmark-report.md
```

> **Note:** The summarizer script is part of the R4.S6 implementation PR
> that ships when this runbook first runs. The script is a thin wrapper
> that reads the two k6 `summary-export` JSONs, extracts the p50/p95/p99
> + RPS + error-rate trends, and renders a markdown comparison table.
> Until that PR lands, the operator computes the table by hand from
> `k6`'s console output and pastes it under the same path. This is the
> ONE place a temporary hand-edit is acceptable per ADR-0029 — and only
> until the summarizer script lands.

## Step 5 — Commit + update ADR-0031

The two generated reports
(`docs/operations/eval-report.md` for quality,
`docs/operations/retrieval-benchmark-report.md` for latency) plus an
appended "Benchmark result (YYYY-MM-DD)" section in
[`ADR-0031`](../../architecture/adr/0031-retrieval-service-extraction.md)
form the artifact set for R4.S6. Commit them together in a single PR
titled "R4.S6: retrieval-transport benchmark".

The ADR section is written by the operator after reading the reports —
this is interpretation, not data, so it doesn't fall under the no-
hand-edits rule.

## Decision rule

Flip the chart's `RETRIEVAL_TRANSPORT` default from `http` (where it
already sits in `values.yaml`) to `in-process` (the safer default
for fresh deployments) **only if** the HTTP path's p95 exceeds
`SLO.queryP95Ms` (currently 4000 ms in
`tests/performance/k6/lib/config.js`). Otherwise the HTTP path stays
the default — the latency cost of one extra in-cluster hop is the
price of the topology and shouldn't be > 100 ms in practice.

## Troubleshooting

- **k6 returns lots of 503s on the http side.** The retrieval pods
  haven't started yet, or `RETRIEVAL_SERVICE_TOKEN` isn't seeded. The
  R6 startup guard in `apps/api/app/lifecycle.py::_build_retrieval_client`
  would normally have failed the API pod's boot — check that you ran
  with `RETRIEVAL_TRANSPORT=in-process` for the in-process release
  and the token is in the http release's ExternalSecret.
- **Quality deltas > 0.02.** Likely cause: the two API deployments
  point at different Postgres / different MinIO. Sanity-check by
  running `SELECT COUNT(*) FROM document_chunks WHERE tenant_id =
  $TENANT` from a pod in each namespace — they must agree.
- **k6 thresholds fire mid-run.** Investigate whether the Ollama pod
  is shared between the two namespaces — generation latency variance
  swamps retrieval-transport variance. Pin Ollama to a separate
  namespace or run sequentially with a 5-min gap.

## References

- [ADR-0031](../../architecture/adr/0031-retrieval-service-extraction.md) —
  the retrieval-service extraction; this benchmark is its decision-rule input
- [ADR-0029](../../architecture/adr/0029-portfolio-polish.md) — harness-
  generated reports; no hand-edited numbers
- [REMEDIATION_PLAN.md § Phase R4](../../architecture/REMEDIATION_PLAN.md) —
  R4.S6 status
- `tests/performance/evals/compare.py` — quality side
- `tests/performance/k6/transport-compare.js` — latency side
