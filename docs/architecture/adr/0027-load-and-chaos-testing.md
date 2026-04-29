# ADR-0027: Load + chaos testing — k6 for load, Chaos Mesh for chaos, hypothesis-driven SLOs

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** testing, resilience, slo, chaos-engineering

## Context

Phase 8 calls for "k6 load tests; chaos tests via litmus or chaos-mesh."
Two real questions:

1. **Tool selection.** k6 vs Locust vs Gatling for load; Chaos Mesh vs
   LitmusChaos vs hand-rolled `kubectl delete pod` loops for chaos.
2. **What to actually assert.** A load test that returns "average
   latency was 1.4 s" is theater — the value comes from binding tests
   to SLO thresholds and steady-state hypotheses that fail loudly when
   broken.

Without a hypothesis, chaos tests are just inducing pain. Without
SLO-bound thresholds, load tests just produce graphs nobody reads.

## Decision

### k6 for load — JS scripts checked into the repo

`tests/performance/k6/` ships four scenarios:

| Script | Cadence | Purpose |
|---|---|---|
| `smoke.js` | every PR | Wiring smoke test (30 s, 0.5 rps). |
| `baseline.js` | release tag | Happy-path regression check (13 m, 5 rps). |
| `soak.js` | weekly | Memory leaks + slow drift (1 h, 3 rps). |
| `spike.js` | release tag | HPA + autoscaler exercise (7.5 m, peak 30 rps). |

Each scenario is JS in the repo with explicit `thresholds` mapped to the
SentinelRAG SLO numbers (`lib/config.js`):

- p95 query latency < **4 s**
- p99 query latency < **8 s**
- error rate < **1 %**

Per-scenario relaxation: spike accepts 2× p99 during the scale-up window;
soak tolerates 1.25× p99 over the hour. These are documented in each
script's header.

### Chaos Mesh for chaos — six narrow experiments

`infra/chaos/experiments/` ships one CRD per failure mode:

| # | Experiment | Hypothesis |
|---|---|---|
| 01 | Pod kill — api | PDB + HPA absorb; p95 unchanged |
| 02 | Network delay — api → Postgres (200 ms) | p99 < 8 s; no pool exhaustion |
| 03 | Network partition — api → Redis (2 min) | Cache fallback works; no 5xx |
| 04 | Network partition — api → Temporal | /query unaffected; ingestion fails fast |
| 05 | DNS chaos — api → Keycloak | JWKS cache TTL covers it; fail-fast after |
| 06 | CPU stress — temporal-worker | Activities throttle, never crash |

A `Workflow` chains all six into a ~35-minute game-day.

### Tying the two together

The k6 baseline scenario IS the assertion. The chaos workflow IS the
perturbation. Run them in parallel against the same cluster:

```
[ Terminal 1 ] kubectl apply -f infra/chaos/workflows/game-day.yaml
[ Terminal 2 ] k6 run tests/performance/k6/baseline.js
```

If the hypotheses hold, k6's thresholds pass — exit 0. If a hypothesis
breaks, k6 fails the run with the specific threshold name in the
output. We get a binary "did the system survive" answer, not 12 graphs
to interpret.

### Why not Locust / LitmusChaos

**k6 over Locust.** k6 scripts are JS, not Python — no concern about
GIL contention biasing latency measurements; the runner's pacing is
correct under heavy concurrent VU counts. k6 also has first-class
Prometheus remote-write output that drops scenario results straight
into the Phase 6 observability stack.

**Chaos Mesh over LitmusChaos.** Both are good. Chaos Mesh has stronger
pod-level network primitives (per-pod tc / iptables via the
chaos-daemon DaemonSet), simpler CRD shape, and a better dashboard.
LitmusChaos is more flexible at the workflow layer but the surface area
isn't worth it for a six-experiment matrix.

### Why not gating CI on full load tests

Only `smoke.js` runs on PR. The full baseline / soak / spike scenarios:

- Need a deployed dev environment, not a CI-spawned ephemeral cluster.
  The 13-minute baseline against a kind cluster proves nothing useful.
- Cost real LLM tokens. Even on Ollama-local, a 10-minute baseline at
  5 rps consumes meaningful CPU that doesn't fit a free CI tier.
- Shouldn't gate every commit. Perf regressions are caught at release
  time when the dev environment is settled, not on every "fix typo" PR.

The smoke run is the only CI gate; it proves the chart + cluster +
auth wiring are alive. The other scenarios are operator-invoked and
release-tagged.

## Consequences

### Positive

- One tool per concern; no mocking the LLM in load tests means we
  measure the real production tail.
- Hypothesis-driven chaos manifests carry their assertions in their
  filename headers — anyone reading the repo understands what each
  experiment is asserting without external docs.
- The k6/Chaos Mesh combination is the recruiter-recognizable shape
  for "production-grade resilience testing." Both tools are CNCF /
  industry-standard.

### Negative

- We don't have continuous load running in CI. A subtle p99 regression
  could land in main and only show up at the next release-tag run.
  Mitigated by the daily perf-smoke cron + Grafana SLO panels showing
  live latency from real traffic on dev.
- Chaos Mesh adds a second control plane in the cluster (chaos-daemon
  DaemonSet). Operationally cheap but real.

### Neutral

- The chaos experiments target labels stamped by the Helm chart. They
  do not work against ad-hoc `kubectl run` pods — by design.

## Alternatives considered

### Option A — Locust (Python) for load
- **Pros:** Python ecosystem; familiar.
- **Cons:** GIL biases concurrency; less faithful pacing; weaker
  Prometheus output story.
- **Rejected because:** k6 is the better fit for HTTP load + Prometheus.

### Option B — LitmusChaos for chaos
- **Pros:** GitOps-native; richer experiment library.
- **Cons:** Heavier CRD shape; more YAML for the same six experiments.
- **Acceptable alternative:** if Chaos Mesh ever has an unfixed
  daemon-side issue, swap in 1 day. Hypothesis files transfer 1:1.

### Option C — Hand-rolled `kubectl delete pod` + `tc` chaos in a bash script
- **Pros:** zero new tooling.
- **Cons:** brittle; no labels-based selector; no game-day workflow
  primitive; recruiter-bad signal.
- **Rejected because:** reinvents Chaos Mesh badly.

## Trade-off summary

| Dimension | k6 + Chaos Mesh (this) | Locust + LitmusChaos | Hand-rolled scripts |
|---|---|---|---|
| Hypothesis-bound assertions | yes (k6 thresholds) | yes (Locust assertions) | no |
| CI smoke gate cost | low | medium (Python deps) | low |
| Recruiter signal | strong | strong | weak |
| Operational footprint | 1 daemonset + 1 namespace | 2 controllers | none |
| Tool churn risk | both CNCF, active | both CNCF, active | none |

## Notes on the design docs

`Enterprise_RAG_Deployment.md` §17 referenced "load tests" without
naming a tool. This ADR commits to k6 + Chaos Mesh and ties both to
the SLO numbers from the PRD (§9 SLOs).

## References

- [k6](https://k6.io/docs/) — Grafana Labs, CNCF
- [Chaos Mesh](https://chaos-mesh.org/) — CNCF graduated
- [Principles of Chaos Engineering](https://principlesofchaos.org/)
- ADR-0023: Helm chart shape — labels we select on
- Phase 6 observability stack — Prometheus + Grafana the k6 output
  feeds into
