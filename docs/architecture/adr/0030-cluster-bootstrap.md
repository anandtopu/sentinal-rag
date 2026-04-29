# ADR-0030: Cluster bootstrap pattern — values overlays + ArgoCD Application manifests, not bundled into the SentinelRAG chart

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** k8s, deployment, gitops, helm, argocd

## Context

ADR-0012 picked Helm + ArgoCD as the deployment toolchain. ADR-0023
shipped the SentinelRAG Helm chart and explicitly excluded Temporal
(its sub-chart graph is too heavy) and the cluster-level operators
(cert-manager, ESO, ArgoCD) from the chart's dependency tree. That
decision left a real question unanswered: **how do those bootstrap
charts get installed, exactly?**

Phase 7 Slice 3 was deferred from the earlier sessions; the deployment
runbooks (Phase 9 follow-up) made it concrete that we needed to commit:

- **What** bootstrap charts run.
- **Pinned versions** so the deploy procedure is reproducible.
- **Per-cloud differences** in their values (IRSA vs Workload Identity,
  Ingress class, ClusterSecretStore CRD shape).
- **Where the values live** so an operator can `helm install -f <file>`
  without inventing one from upstream defaults each time.
- **The ArgoCD Application manifest** that ties the chart at
  `infra/helm/sentinelrag/` to a deployed environment.

Three plausible options came up:

1. **Bundle every bootstrap chart into the SentinelRAG chart's
   `dependencies:`** — one `helm install`, every layer comes up at once.
2. **Manage every bootstrap chart from ArgoCD itself** (an
   ApplicationSet that fans out cert-manager + ESO + ArgoCD-itself + …)
   — pure GitOps, recursive.
3. **Commit values overlays + an ArgoCD Application manifest as
   plain files; document the install order in a runbook.** Operator
   runs `helm install` per layer in order, then ArgoCD takes over for
   the SentinelRAG chart only.

## Decision

We picked option 3.

### Layout

```
infra/bootstrap/
├── README.md                                  # the layout + version pins
├── cert-manager/values.yaml
├── aws-load-balancer-controller/values.yaml   # AWS only
├── external-secrets/
│   ├── values.yaml
│   ├── secret-store-aws.yaml                  # ClusterSecretStore (apply after ESO is up)
│   └── secret-store-gcp.yaml
├── temporal/values.yaml
├── argocd/
│   ├── values.yaml
│   └── applications/
│       ├── sentinelrag-dev.yaml               # AWS dev
│       └── sentinelrag-gcp-dev.yaml           # GCP dev
└── chaos-mesh/values.yaml                     # optional — for Phase 8 game-day
```

The runbook at `docs/operations/runbooks/cluster-bootstrap.md` documents
the install order (cert-manager → AWS LB controller → ESO + secret-store
→ Temporal → ArgoCD → SentinelRAG Application) and the canonical `helm
install` invocation per chart with the version pinned.

### Per-cloud differences — flagged inline, not forked

The values files are mostly cloud-agnostic. Where they differ (e.g.
ESO's ServiceAccount needs `eks.amazonaws.com/role-arn` on AWS but
`iam.gke.io/gcp-service-account` on GCP), the values file carries
**both annotations as comments** and asks the operator to swap. This
is grimy, but only one or two annotations per file are involved, and
forking values per cloud creates more drift over time.

The ArgoCD Application manifest IS forked per cloud
(`sentinelrag-dev.yaml` vs `sentinelrag-gcp-dev.yaml`) because the
values file reference (`values-dev.yaml` vs `values-gcp-dev.yaml`)
genuinely differs and the file is short anyway.

### Pinned versions in the runbook, not in YAML

Each `helm install` in the runbook pins its `--version`. We did not put
the version into the values file (Helm doesn't actually consume that)
or into a top-level lock file. The runbook is the source of truth for
"what version was installed" because the runbook is what the operator
literally runs.

The pinned-version table is duplicated at `infra/bootstrap/README.md`
for convenience; bumping a version is a documented two-step (update
the runbook line, update the README table) — small enough to live with.

### Image build → GHCR → ArgoCD Image Updater

`.github/workflows/build-images.yml` builds the three SentinelRAG
images on every push to `main` (tag: `:sha-<short>`) and on every git
tag matching `v*.*.*` (tag: `:vX.Y.Z`). It pushes to GHCR with
provenance attestation + SBOM via `actions/attest-build-provenance`.

ArgoCD Image Updater (configured via annotations on the Application
manifest) watches GHCR for tags matching `^v\d+\.\d+\.\d+$` and bumps
the image references in the Helm values. We use **Git write-back**
mode so the bump is a real commit on `main` — auditable, revertable.

### What we did NOT do

- **Did not put the bootstrap charts into the SentinelRAG chart's
  `dependencies:`.** ADR-0023 already decided that. Re-stated here:
  the SentinelRAG chart re-deploys on every commit; the bootstrap
  charts re-deploy at most once per cluster. Different lifecycles
  belong in different artifacts.
- **Did not manage ArgoCD-itself with ArgoCD.** Chicken-and-egg: if
  ArgoCD is broken, you can't fix ArgoCD via ArgoCD. We accept the
  small ops surface of `helm install argocd ...` once per cluster.
  An ApplicationSet for the rest of the bootstrap stack is a Phase
  9-or-later improvement.
- **Did not commit a Terragrunt-style meta layer.** Same reasoning as
  ADR-0024 — at our scope it adds tool surface without payoff.

## Consequences

### Positive

- A new operator can deploy the platform by following one runbook and
  copy-pasting from the values overlays. No guessing what the right
  upstream defaults are.
- Bumping a chart version is a deliberate two-line commit (runbook +
  bootstrap README). Easy to audit.
- The SentinelRAG chart stays small and ArgoCD-managed; the
  one-and-done stack stays operator-managed. Two lifecycles, two tools.
- The Application manifests live in the same repo as the chart, so a
  PR that changes both the values and the Application annotations is
  one diff.

### Negative

- The "swap one annotation when deploying to GCP" step in
  `external-secrets/values.yaml` is a small foot-gun. We mitigate by
  keeping both annotations as comments in the file and documenting
  the swap in the GCP runbook.
- `helm upgrade --install` is operator-driven, not GitOps. A drift in
  the bootstrap stack between commits is invisible until someone
  re-applies. Acceptable trade-off — the bootstrap stack changes rarely.
- We don't manage observability (OTel collector, Tempo, Prom, Loki) as
  bootstrap values yet. The SentinelRAG chart references the collector;
  installing it remains the operator's responsibility per upstream docs.
  Phase 9 polish will add a values overlay here.

### Neutral

- Pinned chart versions are the runbook's job, not the chart's. This
  means a `helm install` outside the runbook can install a different
  version. Operators who do that are on their own — same as anywhere
  else.

## Alternatives considered

### Option A — Bundle the bootstrap charts as SentinelRAG dependencies
- **Pros:** one `helm install`.
- **Cons:** every SentinelRAG release re-renders ArgoCD + ESO + Temporal,
  which doesn't make sense; Helm's dependency graph isn't designed for
  cluster operators. Already rejected by ADR-0023.
- **Rejected because:** different lifecycles.

### Option B — Pure GitOps via ArgoCD ApplicationSet for the whole stack (including ArgoCD itself)
- **Pros:** drift is detected automatically; bumping a version is a
  PR not a `helm upgrade`.
- **Cons:** ArgoCD-managing-ArgoCD is operationally fragile (broken
  ArgoCD → broken ArgoCD recovery). The recovery flow is "delete the
  Application that manages ArgoCD then helm-install manually" — an
  extra step that obscures the failure.
- **Acceptable alternative:** if ArgoCD's self-management story matures
  (or if we add a Cluster API layer that owns ArgoCD), revisit. Phase
  10+.

### Option C — Operator-driven shell script that wraps `helm install`
- **Pros:** zero new tooling; reproducibility encoded in code.
- **Cons:** the runbook IS that script in prose form, with explanation;
  encoding it as bash hides the why behind the what.
- **Rejected because:** the runbook serves both as operator procedure
  and as documentation; a script is just one of those.

## Trade-off summary

| Dimension | Values overlays + runbook (this) | Bundle into SentinelRAG chart | Pure ApplicationSet GitOps |
|---|---|---|---|
| Deploy granularity | per-layer, per-runbook-step | one `helm install` | per-Application |
| Drift detection on bootstrap stack | manual | n/a (re-deploys with app) | automatic |
| Operator reading load | runbook (~600 lines) | values (~200 lines) | ApplicationSet + values |
| Recursive failure cost | low | n/a | high (broken ArgoCD breaks ArgoCD recovery) |
| Per-cloud difference handling | inline annotations + forked Application | sub-chart per cloud | ApplicationSet generators |

## Notes on the design docs

`Enterprise_RAG_Deployment.md` §15 originally specified `kubectl apply -k`
from CI for the bootstrap stack. ADR-0012 already replaced that with
Helm + ArgoCD for the application; this ADR pins the bootstrap-stack
shape for the platform layer.

## References

- ADR-0011 — Multi-cloud strategy
- ADR-0012 — Helm + ArgoCD GitOps
- ADR-0023 — SentinelRAG Helm chart shape (excludes bootstrap charts)
- ADR-0025 — GCP parity
- `docs/operations/runbooks/cluster-bootstrap.md` — the procedural
  manifestation
- `docs/operations/runbooks/deployment-{aws,gcp}.md` — the per-cloud
  end-to-end deploy procedures
