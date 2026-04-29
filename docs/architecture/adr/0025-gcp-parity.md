# ADR-0025: GCP parity strategy — module-name parity, identical Helm chart, single values overlay differs

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** multi-cloud, gcp, terraform, helm

## Context

ADR-0011 committed us to AWS primary + GCP mirror. Phase 7 shipped the AWS
Terraform; Phase 8 builds the GCP equivalent. The CLAUDE.md rule is firm:
"Helm chart is the single deployment artifact … manifests must be identical
AWS↔GCP. If you find yourself writing cloud-specific K8s, it belongs in a
Helm value override, not a fork."

Two real questions came up while writing the GCP code:

1. **Module-name strategy.** Should GCP modules use cloud-native names
   (`compute_network`, `gke_cluster`, `cloud_sql`) or AWS-equivalent names
   (`vpc`, `eks`, `rds`)? Cloud-native names match the GCP docs the operator
   reads when debugging; equivalent names make the env `main.tf` read
   identically across clouds.
2. **How tightly should the Helm values mirror?** AWS uses IRSA via
   `eks.amazonaws.com/role-arn` SA annotations; GCP uses Workload Identity
   via `iam.gke.io/gcp-service-account`. Different annotation key, different
   value shape. Same idea, but they cannot be a single template.

## Decision

### Module names: function-first, not vendor-first

GCP modules use **functional** names that match their AWS counterparts:

| Function | AWS module | GCP module |
|---|---|---|
| Network | `vpc` | `vpc` |
| K8s cluster | `eks` | `gke` |
| RDBMS | `rds` | `cloudsql` |
| Cache | `elasticache` | `memorystore` |
| Object storage | `s3` | `gcs` |
| Secrets | `secrets` | `secrets` |
| Workload identity | `iam` | `iam` |

`vpc`, `secrets`, and `iam` are name-identical because the function maps
1:1. The data-plane modules use vendor-recognizable names because that's
what GCP operators search for in tooling (logs, gcloud, GCP console).

The trade-off: you lose "drop-in module swap" — `module "rds"` and
`module "cloudsql"` aren't interchangeable. You gain searchability and
operator clarity. We picked operator clarity.

### Helm values: shared chart, per-cloud overlays

The Helm chart is the same. We don't introduce sub-charts, conditionals,
or template-time cloud detection beyond what ADR-0023 already specified
(`cloud: aws | gcp | azure | local` controls default IngressClass). What
differs per cloud:

- **ServiceAccount annotations** — IRSA on AWS, Workload Identity on GCP.
  The chart uses an opaque `serviceAccount.annotations` map; each overlay
  fills in cloud-native annotation keys.
- **Ingress class + annotations** — `alb` on AWS (with ALB-controller
  annotations), `gce` on GCP (with managed-cert + static-IP annotations).
- **Object storage provider** — `s3` (AWS) vs `gcs` (GCP). The shared
  `ObjectStorage` interface in `sentinelrag_shared/object_storage/`
  already abstracts this; values just route the right provider name.
- **Bucket names + DSN hostnames** — different per cloud, expected.

### Identity model

| AWS | GCP |
|---|---|
| OIDC provider on the cluster | Workload Identity pool `<project>.svc.id.goog` |
| IAM role with trust policy on `system:serviceaccount:ns:sa` | GSA + `roles/iam.workloadIdentityUser` binding to KSA |
| `eks.amazonaws.com/role-arn` annotation | `iam.gke.io/gcp-service-account` annotation |

Both flows produce a workload-scoped identity at the pod level with no
long-lived credentials in the container. Implementation diverges; the
guarantee is the same.

### Audit immutability

| AWS | GCP |
|---|---|
| S3 Object Lock COMPLIANCE mode, 7y retention | GCS bucket retention policy, 7y, locked |

Both are real immutability — root/project-owner cannot delete the data
within retention. Neither is just a soft "default policy" — both require
explicit lock that prevents the owner from later weakening the policy.

ADR-0016 (audit dual-write) is upheld on both clouds.

### What we did NOT do

- **Did not add cloud-detection in the chart templates.** The `cloud:` key
  only drives the default IngressClass; everything else is per-overlay.
- **Did not write a Workload-Identity-vs-IRSA abstraction.** The two
  annotation flavors are 30 lines of overlay yaml each — abstraction
  costs more than it saves.
- **Did not introduce a multi-cloud Terraform "facade" module.** The env
  `main.tf` files differ per cloud (AWS uses ALB controller, GCP uses
  managed cert + Cloud NAT) — collapsing them under one façade would
  hide details that matter when debugging an apply.

## Consequences

### Positive

- One chart, two clouds. Adding a third (Azure, when it gets promoted out
  of ADR-only status per ADR-0011) is a values overlay + Terraform module
  set — no chart edits.
- Functional module names make `infra/terraform/<cloud>/environments/dev/main.tf`
  read like a parallel-text translation: same modules, same call shape,
  cloud-specific deps swapped in.
- Each cloud's Terraform stays idiomatic — no leaky abstractions trying to
  unify GKE node pools with EKS node groups.

### Negative

- Overlays drift. `values-dev.yaml` and `values-gcp-dev.yaml` carry the
  same env-vars + image tags duplicated. We accept ~80 lines of yaml
  duplication per overlay over the alternative.
- An operator who knows AWS doesn't get a free pass on GCP — they still
  have to learn Workload Identity, Cloud NAT, PSA, etc. Documenting the
  AWS↔GCP map explicitly in `infra/terraform/gcp/README.md` is the
  mitigation.

### Neutral

- Helm chart's `_helpers.tpl` doesn't grow new helpers for GCP. The
  cloud-switch mechanism that ADR-0023 already shipped is enough.

## Alternatives considered

### Option A — Crossplane / Pulumi for cross-cloud modules
- **Pros:** One module that targets either cloud.
- **Cons:** New tool; abstraction tends to leak; harder to read raw
  resources during incidents.
- **Rejected because:** the abstraction overhead is bigger than the
  duplication it saves.

### Option B — Cluster API + Helm-only definitions
- **Pros:** Cluster API standardizes K8s provisioning across clouds.
- **Cons:** Still need Terraform for non-K8s resources (RDS, Cloud SQL,
  etc.). Doubles the tooling.
- **Rejected because:** marginal value for our scope.

### Option C — Single Terraform module that fans out to both clouds via providers
- **Pros:** apply-once.
- **Cons:** state file becomes the blast radius for a misconfigured
  variable on one cloud taking down the other.
- **Rejected because:** isolation per cloud is a feature.

## Trade-off summary

| Dimension | This ADR (per-cloud Terraform, shared chart) | Crossplane | Single multi-cloud Terraform |
|---|---|---|---|
| Operator readability | high (idiomatic per cloud) | medium | low |
| Module duplication | ~7 modules per cloud | minimal | none |
| Blast radius isolation | per-env, per-cloud state | shared | shared |
| Onboarding cost | learn each cloud | learn Crossplane CRDs | learn the abstraction |

## Notes on the design docs

`Enterprise_RAG_Folder_Structure.md` already sketched
`infra/terraform/{aws,gcp}/...` — this ADR commits to module-name parity
plus a single shared Helm chart with per-cloud values overlays.

## References

- ADR-0011: Multi-cloud strategy (AWS primary, GCP mirror)
- ADR-0012: Helm chart + ArgoCD
- ADR-0023: Helm chart shape — single chart with cloud switch
- ADR-0024: Terraform layout — env-per-dir + shared modules
- ADR-0016: Audit dual-write to Postgres + immutable object storage
