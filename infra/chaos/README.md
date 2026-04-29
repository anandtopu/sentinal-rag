# SentinelRAG — Chaos engineering

Chaos Mesh manifests that exercise the SentinelRAG resilience hypotheses
documented in ADR-0027. Each manifest carries a `Hypothesis:` block in its
header so the experiment is self-documenting.

## Layout

```
infra/chaos/
├── namespace.yaml                          # sentinelrag-chaos ns
├── experiments/
│   ├── 01-pod-kill-api.yaml
│   ├── 02-network-delay-postgres.yaml
│   ├── 03-network-partition-redis.yaml
│   ├── 04-network-partition-temporal.yaml
│   ├── 05-dns-chaos-keycloak.yaml
│   └── 06-stress-cpu-worker.yaml
└── workflows/
    └── game-day.yaml                       # chained sequence (~35 min)
```

## Experiment matrix

| # | Experiment | Target | Hypothesis (steady-state) |
|---|---|---|---|
| 01 | Pod kill | api | p95 unchanged; PDB+HPA absorb the loss |
| 02 | Network delay | api → Postgres (200 ms) | p99 < 8 s; no pool exhaustion |
| 03 | Network partition | api → Redis (2 min) | /query degrades 1.5×; no 5xx |
| 04 | Network partition | api → Temporal frontend | /query unchanged; ingestion fails fast |
| 05 | DNS chaos | api → Keycloak hostname | /query OK during JWKS cache TTL; fail-fast after |
| 06 | CPU stress | temporal-worker (80% × 2 cores) | Activities complete; no pod restarts |

## Prerequisites

1. Chaos Mesh installed in the cluster (`chaos-mesh` namespace).
   Recommended via the official Helm chart:
   ```
   helm repo add chaos-mesh https://charts.chaos-mesh.org
   helm install chaos-mesh chaos-mesh/chaos-mesh \
     -n chaos-mesh --create-namespace
   ```
2. `kubectl` context pointed at the dev cluster (NEVER prod without
   explicit approval).
3. The SentinelRAG workloads are running with the standard labels the
   experiments select on (`app.kubernetes.io/component={api,temporal-worker}`,
   `app.kubernetes.io/part-of=sentinelrag`). The Helm chart's
   `_helpers.tpl` already stamps these.

## Running a single experiment

```bash
# Apply the namespace first (one-time).
kubectl apply -f infra/chaos/namespace.yaml

# Run experiment 01.
kubectl apply -f infra/chaos/experiments/01-pod-kill-api.yaml

# Watch effects.
kubectl -n sentinelrag-chaos describe podchaos api-pod-kill
kubectl -n sentinelrag get pods -l app.kubernetes.io/component=api -w

# Tear down.
kubectl delete -f infra/chaos/experiments/01-pod-kill-api.yaml
```

## Running the full game-day workflow

```bash
# In one terminal, kick off the chaos workflow (~35 min).
kubectl apply -f infra/chaos/workflows/game-day.yaml
kubectl -n sentinelrag-chaos describe workflow game-day-001

# In a second terminal, run k6 baseline against the same cluster.
k6 run \
  -e SENTINELRAG_BASE_URL=https://api.dev.sentinelrag.example.com \
  -e SENTINELRAG_AUTH_TOKEN=$(./scripts/mint-keycloak-token.sh dev) \
  -e SENTINELRAG_COLLECTION_IDS=$(./scripts/list-demo-collections.sh dev) \
  tests/performance/k6/baseline.js
```

The k6 thresholds in `baseline.js` will FAIL the run if the resilience
hypotheses break. That's the point — the load test is the assertion;
the chaos workflow is the perturbation.

## Reading the results

Three places to look:

1. **k6 summary** — pass/fail of the SLO thresholds. If error rate
   stayed under 1 % and p99 stayed within budget, the hypothesis held.
2. **Grafana → rag-overview** — pre/during/post panels for each
   experiment, tagged via `experiment=<name>` annotations on the
   chaos events.
3. **`audit_events` table + S3 audit bucket** — count of `query.executed`
   vs `query.failed` events during the experiment window proves the
   `audit_events` write path didn't itself become a failure mode.

## Safety

- These manifests target **`app.kubernetes.io/part-of: sentinelrag`** labels.
  They will not touch other workloads in the cluster.
- The `sentinelrag-chaos` namespace is a clean blast radius — RBAC can
  be locked down so only chaos engineers / SREs can apply CRDs into it.
- Do NOT run the audit bucket retention or RDS deletion-protection in
  the chaos scope. We do not chaos-test data integrity guarantees with
  this tooling — those are tested via DR drills (Phase 9).
- Disable / pause the workflow in production: edit `spec.deadline` to
  zero, or just `kubectl delete workflow game-day-001 -n sentinelrag-chaos`.

## Adding a new experiment

1. Pick a single, narrow failure mode. One blast radius per CRD.
2. Write the hypothesis as the file header (`# Hypothesis: ...`).
3. Define the steady-state metric — what k6 / Grafana should show if the
   hypothesis holds.
4. Add an entry to the matrix in this README.
5. Append it to the `game-day.yaml` workflow's children list.

References: [Chaos Mesh docs](https://chaos-mesh.org/docs/),
[Principles of Chaos Engineering](https://principlesofchaos.org/).
