# ADR-0024: Terraform layout — env-per-dir + shared module library, no Terragrunt

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** terraform, deployment, multi-cloud

## Context

Phase 7 needed to land AWS Terraform alongside the Helm chart. The repo's
target structure (`Enterprise_RAG_Folder_Structure.md`) sketched
`infra/terraform/{aws,gcp}/{environments,modules}` but didn't pin the
inter-environment composition pattern. Three real options came up:

1. **Env-per-dir + shared modules** (what we shipped). One root module per
   environment under `environments/<env>/`, importing reusable building
   blocks from `modules/`. Each env has its own `.tfstate`, its own
   provider config, its own variable file.
2. **Terragrunt** for DRY — a wrapper that lets each env be a 5-line stub
   referencing a single canonical root.
3. **Workspaces** — one root module, swap state via
   `terraform workspace select`.

ADR-0011 already commits us to AWS-primary + GCP-mirror and warns: "if you
find yourself writing cloud-specific K8s, it belongs in a Helm value
override, not a fork." That instinct (avoid forks) pushes toward DRY. But
infra is messier than K8s — different clouds, different account IDs,
different region constants, different blast radii.

## Decision

### Env-per-dir with a shared `modules/` library

```
infra/terraform/aws/
├── modules/
│   ├── vpc/        # 3-AZ VPC + NAT
│   ├── eks/        # cluster + nodes + OIDC
│   ├── rds/        # Postgres 16 + pgvector
│   ├── elasticache/# Redis 7
│   ├── s3/         # documents + audit (Object Lock)
│   ├── secrets/    # Secrets Manager
│   └── iam/        # IRSA roles
└── environments/
    ├── dev/        # main.tf composes modules; own .tfstate
    ├── staging/    # (Phase 8)
    └── prod/       # (Phase 8)
```

GCP gets the same shape under `infra/terraform/gcp/` (Phase 8). Module names
match across clouds (`vpc`, `kubernetes`, `database`, `cache`, `storage`,
`secrets`, `iam`) so the env-level `main.tf` reads almost identically.

### Module conventions

- Every module pins `terraform >= 1.7.0` + `aws >= 5.50.0, < 6.0.0`.
- Every module accepts `var.tags` and merges them onto every resource.
- Every module uses a single `name` (or `name_prefix`) variable so the
  whole stack is namespaced for the environment (`sentinelrag-dev-*`).
- Secrets are passed *in* via vars marked `sensitive = true`; modules never
  generate them. Long-term values live in Secrets Manager / RDS console
  and `lifecycle.ignore_changes` keeps Terraform from clobbering them on
  rotation.

### Remote state per environment

Each env has its own S3 backend bucket key
(`aws/<env>/terraform.tfstate`) with DynamoDB locking. The bucket itself
must be bootstrapped manually — chicken-and-egg. Documented in
`infra/terraform/aws/README.md`.

### No Terragrunt

We rejected Terragrunt despite its DRY appeal. The cost-of-second-tool
exceeds the wins for our 3-env, 2-cloud scope:

- One more dependency to install in CI and locally.
- One more thing recruiters / new contributors have to learn before they
  can `terraform plan`.
- The "DRY" payoff per env file is ~30 lines of provider + backend config
  duplicated across 3 envs — small enough to live with.

If the matrix grows past ~6 envs × 2 clouds, revisit.

### No workspaces

Workspaces share a root module but split state. They make
"is dev or prod different here?" questions hard to answer: the answer
depends on `terraform.workspace`, which is a runtime string. Operators
can't grep for "what's in prod" by reading a single file. Env-per-dir is
self-documenting; workspaces are not.

## Consequences

### Positive

- A new env is a directory copy + variables tweak. Nothing else.
- `terraform plan` in `environments/dev/` is hermetic — no global state
  bleed.
- Each env's `outputs.tf` is the contract surface for the chart's
  values overlay (IRSA role ARNs, RDS endpoints, bucket names).

### Negative

- Provider + backend config are duplicated per env (~30 lines each). If
  we add a fourth env, this pain compounds linearly.
- Cross-env coordination (e.g. shared KMS key in a `core` env that
  dev/staging/prod consume) needs explicit `data` lookups by ARN, not a
  module reference.

### Neutral

- The chart's `values-{env}.yaml` consumes Terraform outputs by hand —
  not auto-wired. This is fine: the chart is the single deployment artifact
  (per ADR-0012) and shouldn't depend on Terraform being applied locally.
  Operators paste IRSA ARNs from `terraform output` into the values file
  once per env.

## Alternatives considered

### Option A — Terragrunt
- **Pros:** DRY remote-state and provider config; per-env stubs are 5 lines.
- **Cons:** Extra tool, extra learning curve, worth it only at >6 envs.
- **Rejected because:** scope doesn't justify it.

### Option B — Workspaces
- **Pros:** One root module to maintain.
- **Cons:** Runtime-string env selection makes auditing harder; sharing a
  root module across dev + prod amplifies blast radius of any change.
- **Rejected because:** it actively hurts auditability for a portfolio
  project.

### Option C — Single monolithic root + `count = var.is_prod ? 1 : 0`
- **Pros:** zero ceremony.
- **Cons:** anti-pattern; one wrong variable flips you between dev and
  prod resources.
- **Rejected because:** unsafe.

## Trade-off summary

| Dimension | Env-per-dir (this) | Terragrunt | Workspaces |
|---|---|---|---|
| Boilerplate per env | ~30 LOC | ~5 LOC | 0 LOC |
| Tool count | 1 | 2 | 1 |
| Auditability | grep-friendly | requires Terragrunt fluency | runtime-string-driven |
| Blast radius isolation | per-dir state | per-dir state | shared root, split state |
| Onboarding cost | low | medium | low (until something breaks) |

## Notes on the design docs

`Enterprise_RAG_Folder_Structure.md` already sketched
`environments/{dev,staging,prod}` and `modules/` directories — this ADR
just commits to *how* they compose.

## References

- [Terraform recommended directory structure](https://developer.hashicorp.com/terraform/language/modules/develop/structure)
- ADR-0011: Multi-cloud strategy (AWS primary, GCP mirror)
- ADR-0012: Helm + ArgoCD GitOps
