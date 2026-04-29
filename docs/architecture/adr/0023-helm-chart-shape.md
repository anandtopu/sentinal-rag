# ADR-0023: Helm chart shape — single chart, in-template workload blocks, cloud switch

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** k8s, deployment, helm

## Context

ADR-0012 picked Helm + ArgoCD as the deployment toolchain and sketched a chart
shape ("one chart for the whole platform; sub-charts for major components
`api`, `retrieval-service`, `ingestion-service`, `evaluation-service`,
`temporal-worker`, `frontend`"). When Phase 7 actually started building the
chart, two things had become true that ADR-0012 didn't account for:

1. The "retrieval / ingestion / evaluation" sub-services from the original
   folder structure are bundled inside `apps/api` today (ADR-0021 — retrieval
   embedded in-process for v1). The deployable surface is **three** workloads,
   not six: `api`, `temporal-worker`, `frontend`.
2. Each of those workloads has the same template shape — Deployment + SA +
   ConfigMap + (optional) Service / Ingress / HPA / PDB / NetworkPolicy /
   ExternalSecret. Six templates × three workloads = 18 files; sub-charts
   would multiply that by an extra layer of indirection (each sub-chart needs
   its own `Chart.yaml`, `values.yaml`, `templates/_helpers.tpl`) without
   adding any factoring benefit, since the workloads share the same parent
   values (image registry, common labels, observability config).

We also need a single knob that toggles cloud-specific concerns
(Ingress class, ServiceAccount IRSA / Workload-Identity annotations, storage
class) without forking the chart per cloud — Helm chart **must be identical
AWS↔GCP** (per `CLAUDE.md`'s "If you find yourself writing cloud-specific K8s,
it belongs in a Helm value override, not a fork").

## Decision

### Single chart with in-template workload blocks (no sub-charts)

`infra/helm/sentinelrag/` is a single Helm chart. Templates are organized by
workload directory (`templates/api/`, `templates/temporal-worker/`,
`templates/frontend/`, `templates/migrations/`) but they all live in the same
chart and share the same values tree.

A shared template library at `templates/_helpers.tpl` exposes:

- `sentinelrag.workload.fullname` — `<release>-<chart>-<workload>`
- `sentinelrag.workload.labels` / `sentinelrag.workload.selectorLabels` —
  enforce `app.kubernetes.io/component` discipline
- `sentinelrag.workload.image` — resolves
  `<registry>/<workload-image-name>:<tag>` with per-workload tag override
- `sentinelrag.workload.envFrom` — emits the `configMapRef` + `secretRef`
  pair every workload mounts the same way
- `sentinelrag.workload.env` — merges `sharedEnv` + per-workload `env` into
  inline env vars
- `sentinelrag.workload.httpProbes` — renders liveness + readiness probes
  for HTTP workloads
- `sentinelrag.defaultIngressClass` / `sentinelrag.workload.ingressClass` —
  the cloud switch (see below)
- `sentinelrag.podSecurityContext` / `sentinelrag.containerSecurityContext` —
  uniform non-root + drop-ALL caps

Each workload template invokes the helpers with a `ctx` dict that includes
the workload key (`workload` for display, `workloadKey` for the values lookup
since `temporal-worker` ↔ `temporalWorker`).

### Cloud switch

Top-level `cloud: aws | gcp | azure | local` toggles defaults via the
`sentinelrag.defaultIngressClass` helper:

| `cloud` | Default IngressClass |
|---|---|
| `aws`   | `alb` |
| `gcp`   | `gce` |
| `azure` | `azure-application-gateway` |
| `local` | `nginx` |

Every workload's `ingress.className` defaults to this; explicit
`ingress.className` always wins. Cloud-specific annotations
(IRSA, ALB scheme, healthcheck path, WAFv2 ACL) live in the per-environment
`values-{dev,prod}.yaml` overlays — never in the templates themselves.

### Dev dependency charts pulled, Temporal pulled at bootstrap

The chart declares dependencies on `bitnami/postgresql`, `bitnami/redis`,
`bitnami/minio`, `bitnami/keycloak`, `unleash/unleash` — every dep gated by
its own `*.enabled` flag. Local clusters enable all five; AWS dev / prod
disable the data plane (RDS, ElastiCache, S3) but keep Keycloak + Unleash
in-cluster.

**Temporal is excluded from the chart's dependency graph.** Temporal's
official chart pulls Cassandra and Elasticsearch sub-charts that make
`helm template` and `helm dependency build` painfully slow. Temporal is
instead installed by cluster bootstrap (Phase 7 Terraform apply) before
SentinelRAG is deployed. The chart points at
`temporal-frontend.temporal.svc.cluster.local:7233`.

### Migrations as a Helm hook

`templates/migrations/job.yaml` is a `pre-install,pre-upgrade` Helm hook that
runs `alembic upgrade head` against `DATABASE_URL` using the API image (which
already has the venv + migration files). It blocks the rollout until
migrations succeed and is annotated
`helm.sh/hook-delete-policy: before-hook-creation` so the most recent failure
remains inspectable.

### Secrets via External Secrets Operator

`externalSecrets.enabled` toggles per-workload `ExternalSecret` resources.
When on, the chart points at a `ClusterSecretStore` provisioned by Terraform
(AWS Secrets Manager / GCP Secret Manager / Vault). When off, workloads
reference plain `Secret` objects the operator (or local dev) creates by hand.
The chart never bakes secret values into rendered manifests.

The remote-key naming convention is
`{release}/{component}/{KEY}` (e.g. `sentinelrag-dev/api/DATABASE_URL`).

## Consequences

### Positive

- One values tree, one `helm install`, one ArgoCD `Application`. The recruiter
  can read the chart top-to-bottom in 15 minutes.
- The `_helpers.tpl` library means adding a fourth workload (a Phase 8 split
  of retrieval into its own service, say) is ~6 short template files reusing
  the same helpers, not a whole new sub-chart.
- Cloud switch is a single value flip, not a fork.

### Negative

- Templates that conditionally render based on `*.enabled` mean a
  `helm template` against a fully-disabled chart still produces hundreds of
  lines of deps. Mitigated by `helm template -f values-{env}.yaml` always
  using a real overlay.
- Without sub-charts, we can't `helm install <component>` independently. In
  practice ArgoCD syncs the whole chart anyway; this isn't a real cost.

### Neutral

- ADR-0012's "sub-charts for `api`, `retrieval-service`, …" guidance is
  superseded; `api` and `frontend` are sub-trees of the same chart, and the
  retrieval / ingestion / evaluation services don't exist as separate
  deployables until Phase 8.

## Alternatives considered

### Option A — Sub-chart per workload (per ADR-0012)
- **Pros:** Independent versioning per component; component teams could
  release on their own cadence.
- **Cons:** Three sub-charts × six templates each = 18 files of pure
  scaffolding before any workload-specific bits. We don't have component
  teams; one operator owns all three.
- **Rejected because:** indirection without payoff.

### Option B — Library chart + thin wrappers per workload
- **Pros:** Templated reuse via Helm's library chart pattern.
- **Cons:** Library charts are awkward to `helm install`; ArgoCD has to see
  an application chart, not a library. Adds a wrapper layer.
- **Rejected because:** `_helpers.tpl` named templates already give us the
  same factoring with no extra chart.

### Option C — Kustomize + cloud-specific overlays
- **Pros:** Simpler than Helm for static manifests.
- **Cons:** Spec already chose Helm + ArgoCD (ADR-0012); reverting is more
  pain than payoff. Kustomize doesn't give us templated cloud-switch helpers
  cleanly.
- **Rejected because:** ADR-0012 stands.

## Trade-off summary

| Dimension | Single chart (this ADR) | Sub-charts | Library chart |
|---|---|---|---|
| Templates | 18 files in one chart | 18 + 3×scaffolding | 18 + library |
| `helm install` | one | one (via parent) | one |
| Per-workload version | shared | independent | shared |
| Recruiter readability | high | medium | low |
| Adding 4th workload | ~6 template files | new sub-chart | ~6 template files |

## Notes on the design docs

This ADR refines (does not supersede) ADR-0012. ADR-0012's "sub-charts for
api, retrieval-service, ingestion-service, evaluation-service,
temporal-worker, frontend" was written before Phase 1–6 collapsed three of
those services back into `apps/api`. This ADR reflects what shipped.

## References

- ADR-0012: Helm chart + ArgoCD GitOps
- ADR-0021: Retrieval embedded in-process for v1
- [Helm chart best practices](https://helm.sh/docs/chart_best_practices/)
- [Helm named templates](https://helm.sh/docs/chart_template_guide/named_templates/)
