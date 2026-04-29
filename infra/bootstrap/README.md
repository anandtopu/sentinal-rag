# Cluster bootstrap charts

Helm values overlays for the **upstream** Helm charts that must be installed
in a SentinelRAG cluster *before* the application chart at
`infra/helm/sentinelrag/` will deploy successfully.

These charts are **NOT** managed by the SentinelRAG chart itself
(per ADR-0023 — keeping the chart graph small was a deliberate trade-off,
restated in ADR-0030 for the bootstrap shape). They are installed once per
cluster as part of the cluster bootstrap runbook (`docs/operations/runbooks/cluster-bootstrap.md`).

## Layout

```
infra/bootstrap/
├── cert-manager/values.yaml          # cert-manager (both clouds)
├── aws-load-balancer-controller/
│   └── values.yaml                   # AWS only — ALB / NLB ingress controller
├── external-secrets/
│   ├── values.yaml                   # ESO controller itself (cloud-agnostic)
│   ├── secret-store-aws.yaml         # ClusterSecretStore wired to AWS Secrets Manager
│   └── secret-store-gcp.yaml         # ClusterSecretStore wired to GCP Secret Manager
├── temporal/values.yaml              # Temporal cluster (both clouds)
├── argocd/
│   ├── values.yaml                   # ArgoCD itself
│   └── applications/
│       ├── sentinelrag-dev.yaml      # SentinelRAG Application — dev (AWS)
│       └── sentinelrag-gcp-dev.yaml  # SentinelRAG Application — dev (GCP)
└── chaos-mesh/values.yaml            # Chaos Mesh — Phase 8 Slice 3 manifests target this
```

## Why this directory exists

The SentinelRAG chart (`infra/helm/sentinelrag/`) is the **deployable artifact**
for the application. The bootstrap charts are the **platform** the application
runs on. They have completely different lifecycles:

- The SentinelRAG chart re-deploys on every commit (via ArgoCD).
- The bootstrap charts re-deploy at most once per cluster, when their
  upstream version is bumped.

Bundling them into one chart would mean every SentinelRAG release also
re-renders ArgoCD, ESO, etc. — bad for blast radius and deploy speed.

The values files here are **operator-supplied parameters** — they stand in
for the equivalent of an Argo CD ApplicationSet for the platform stack. We
intentionally don't ArgoCD-manage ArgoCD itself in v1 (chicken-and-egg);
that's documented as a Phase-9-or-later improvement in ADR-0030.

## Order of operations

The cluster bootstrap runbook applies these in a strict order so each layer
can find its dependencies:

1. **cert-manager** — issues the certs every other webhook needs
2. **AWS LB controller** _(AWS only)_ — Ingress class `alb`
3. **External Secrets Operator** + ClusterSecretStore (cloud-specific)
4. **Temporal** — own namespace, own RDS instance
5. **ArgoCD** — installed last
6. **ArgoCD Application** for SentinelRAG — points at this repo + values overlay

See `docs/operations/runbooks/cluster-bootstrap.md` for the per-step
`helm install` command.

## Pinned versions

| Chart | Repo | Pinned version |
|---|---|---|
| cert-manager | `https://charts.jetstack.io` | `v1.16.2` |
| aws-load-balancer-controller | `https://aws.github.io/eks-charts` | `1.10.1` |
| external-secrets | `https://charts.external-secrets.io` | `0.10.7` |
| temporal | `https://go.temporal.io/helm-charts` | `0.55.0` |
| argo-cd | `https://argoproj.github.io/argo-helm` | `7.7.5` |
| chaos-mesh | `https://charts.chaos-mesh.org` | `2.7.2` |

These are pinned in the runbook's `helm install` commands. Bumping a
version is a deliberate operator action (see the runbook).

## Related ADRs

- [ADR-0012](../../docs/architecture/adr/0012-helm-argocd-deployment.md) — Helm + ArgoCD
- [ADR-0023](../../docs/architecture/adr/0023-helm-chart-shape.md) — Why these aren't sub-charts
- [ADR-0030](../../docs/architecture/adr/0030-cluster-bootstrap.md) — This directory's shape
