# SentinelRAG — k6 load tests

Four scenarios that target the `POST /api/v1/query` endpoint:

| Script | Purpose | Duration | Steady RPS |
|---|---|---|---|
| `smoke.js` | CI gate; proves the wiring works | 30s | 0.5 |
| `baseline.js` | Pre-release happy-path regression check | 13m | 5 |
| `soak.js` | Memory leaks, slow drift over time | 1h | 3 |
| `spike.js` | HPA + autoscaler exercise | 7.5m | 3 (peaks at 30) |

## Required environment

| Variable | Default | Notes |
|---|---|---|
| `SENTINELRAG_BASE_URL` | `http://localhost:8000` | API service URL |
| `SENTINELRAG_API_BASE` | `/api/v1` | Path prefix |
| `SENTINELRAG_AUTH_TOKEN` | `dev` | Bearer token. Use `dev` only when `AUTH_ALLOW_DEV_TOKEN=true` and `ENVIRONMENT=local` (CLAUDE.md dev-token bypass). For dev/prod, mint a real Keycloak access token. |
| `SENTINELRAG_COLLECTION_IDS` | (empty — required) | Comma-separated collection UUIDs to query. After `make seed`, run `make show-demo-collection-ids`. |

## Running locally

```bash
# Bring up the local stack first.
make up
make seed

# Smoke run — 30s, ~15 requests.
k6 run \
  -e SENTINELRAG_AUTH_TOKEN=dev \
  -e SENTINELRAG_COLLECTION_IDS=<demo-collection-uuid> \
  tests/performance/k6/smoke.js

# Full baseline.
k6 run -e SENTINELRAG_COLLECTION_IDS=<uuid> tests/performance/k6/baseline.js
```

## Running against the dev environment

```bash
TOKEN=$(./scripts/mint-keycloak-token.sh dev demo-admin)
k6 run \
  -e SENTINELRAG_BASE_URL=https://api.dev.sentinelrag.example.com \
  -e SENTINELRAG_AUTH_TOKEN=$TOKEN \
  -e SENTINELRAG_COLLECTION_IDS=$(./scripts/list-demo-collections.sh dev) \
  tests/performance/k6/baseline.js
```

## Streaming results to OTel / Prometheus

`k6` ≥ 0.46 ships an experimental Prometheus remote-write output. The
SentinelRAG observability stack (Phase 6) already exposes a Prometheus
remote-write endpoint, so:

```bash
K6_PROMETHEUS_RW_SERVER_URL=http://prom.dev.sentinelrag.example.com/api/v1/write \
K6_PROMETHEUS_RW_TREND_AS_NATIVE_HISTOGRAM=true \
k6 run --out experimental-prometheus-rw tests/performance/k6/baseline.js
```

This lights up the existing Grafana **rag-overview** dashboard's load-test
panels with each scenario tagged via the `scenario` tag.

## SLO thresholds

`lib/config.js` exposes the canonical SLO targets:

- p95 query latency < **4 s**
- p99 query latency < **8 s**
- error rate < **1 %**

Each script tightens or loosens these per-scenario (spike accepts a 2× p99
during scale-up; soak tolerates a 1.25× p99 over the hour).

## What the scripts intentionally do NOT do

- They do **not** mock the LLM. The tests measure the real end-to-end path
  including LLM generation. To benchmark just retrieval, point `LITELLM_*`
  at a stub model in the API config and skip the generation step.
- They do **not** assert on grounding scores or answer quality. Quality
  regressions belong in the eval suite, not the perf suite — load tests
  with stochastic LLMs flake otherwise.
- They do **not** load the corpus themselves. Run `make seed` to populate
  documents + the demo collection before running.
