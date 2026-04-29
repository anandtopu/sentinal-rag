# SentinelRAG — AWS Terraform

This directory provisions the AWS infrastructure for SentinelRAG. The Helm
chart at `infra/helm/sentinelrag/` is deployed onto the EKS cluster created
here.

## Layout

```
infra/terraform/aws/
├── modules/                 # Reusable building blocks
│   ├── vpc/                 # 3-AZ VPC, public+private subnets, NAT, IGW
│   ├── eks/                 # EKS cluster + managed node group + IRSA OIDC
│   ├── rds/                 # RDS Postgres 16 + pgvector parameter group
│   ├── elasticache/         # Redis 7 replication group
│   ├── s3/                  # documents bucket + audit bucket (Object Lock)
│   ├── secrets/             # Secrets Manager (api / worker / frontend)
│   └── iam/                 # IRSA roles for the workloads + ESO
└── environments/
    ├── dev/                 # Live AWS dev wiring
    ├── staging/             # (Phase 8)
    └── prod/                # (Phase 8)
```

GCP mirror lives at `../gcp/` (Phase 8). Azure is ADR-only — see ADR-0011.

> **Looking for the end-to-end deploy procedure?** See
> [`docs/operations/runbooks/deployment-aws.md`](../../../docs/operations/runbooks/deployment-aws.md)
> for fresh-account → live-URL. This file is the module-by-module
> reference; the runbook is the procedural one.

## Prerequisites

- AWS credentials with admin scope (one-time bootstrap).
- An S3 bucket + DynamoDB table for remote state. Create them by hand once
  per account; the bucket name goes into `backend.tf` via
  `terraform init -backend-config="bucket=..."`.
- Terraform `>= 1.7.0`, AWS provider `>= 5.50.0`.

## Apply order (dev bootstrap)

1. Bootstrap remote state bucket + lock table (one-time, manual).
2. `cd environments/dev && cp terraform.tfvars.example terraform.tfvars`
   and fill in `rds_master_password` + `redis_auth_token`. (These are
   sensitive — gitignored.)
3. `terraform init -backend-config="bucket=sentinelrag-tfstate-<account>"`
4. `terraform plan -out tf.plan && terraform apply tf.plan`
5. Wire kubectl: copy the `kubectl_config_command` output and run it.
6. Install cluster add-ons that aren't shipped via the chart yet (Phase 7
   Slice 3): AWS Load Balancer Controller, External Secrets Operator,
   ArgoCD, Temporal, cert-manager. Each has its own Helm chart pulled
   independently.
7. Install SentinelRAG: `helm install sentinelrag-dev ../../../helm/sentinelrag -f ../../../helm/sentinelrag/values-dev.yaml`
   (or via ArgoCD Application).

## What this provisions (dev)

| Resource | Choice | Module |
|---|---|---|
| VPC | 10.20.0.0/16, 3 AZ public + 3 AZ private, single NAT | `vpc` |
| EKS | v1.30, managed node group, t3.large × 2-6 | `eks` |
| RDS | Postgres 16.4, db.t4g.medium, single-AZ, gp3 50→200 GB | `rds` |
| Redis | ElastiCache 7.1, cache.t4g.small, single shard | `elasticache` |
| S3 | `<prefix>-documents` (versioned) + `<prefix>-audit` (Object Lock COMPLIANCE 7y) | `s3` |
| Secrets Manager | `<release>/api`, `<release>/temporal-worker`, `<release>/frontend` | `secrets` |
| IRSA | api, worker, frontend, eso | `iam` |

Cost note: the dev defaults (single NAT, single-AZ RDS, single-node Redis,
no NAT redundancy) put dev around $200–$300/mo at idle. Prod overlay flips
multi-AZ on across the data plane.

## Module conventions

- Every module pins `required_version >= 1.7.0` and AWS provider
  `>= 5.50.0, < 6.0.0`.
- Every module accepts `var.tags` and merges them onto every resource.
- Naming uses a single `name` (or `name_prefix`) variable so the entire
  stack is namespaced for the environment (e.g. `sentinelrag-dev-*`).
- Secrets are passed *in* (never generated); the lifecycle of the actual
  secret value lives in Secrets Manager / RDS console post-bootstrap.

## Things deliberately not in this layout (yet)

- **OpenSearch** — Phase 8 (ADR-0004). Postgres FTS handles BM25 in v1.
- **Bedrock / VPC endpoint policies** — Phase 8 (LLM gateway hardening).
- **WAFv2 / Shield** — Phase 8.
- **Cross-account state replication** — Phase 9 portfolio polish.
- **Cluster add-ons** (ALB controller, ESO, ArgoCD, Temporal) — Phase 7
  Slice 3 will install these via their own Helm charts after the cluster
  is up.

## Destroy

```
terraform destroy
```

…will fail on the audit bucket because Object Lock blocks deletion of any
versioned object during the 7-year retention. To actually remove a dev
environment, you must wait out retention (yes, really) or manually
`aws s3api delete-objects --bypass-governance-retention` if the lock mode
is GOVERNANCE — but COMPLIANCE mode (the default) cannot be bypassed even
by root. This is the point.
