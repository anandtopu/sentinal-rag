# SentinelRAG — GCP Terraform (mirror)

GCP mirror of the AWS Terraform under `../aws/`. Module names match across
clouds so the env `main.tf` reads similarly. The Helm chart at
`infra/helm/sentinelrag/` is identical between clouds — only the values
overlay (`values-gcp-dev.yaml` vs `values-dev.yaml`) differs.

> **Looking for the end-to-end deploy procedure?** See
> [`docs/operations/runbooks/deployment-gcp.md`](../../../docs/operations/runbooks/deployment-gcp.md)
> for fresh-project → live-URL. This file is the module-by-module
> reference; the runbook is the procedural one.

## Layout

```
infra/terraform/gcp/
├── modules/
│   ├── vpc/         # VPC + subnet + Cloud NAT + PSA reservation
│   ├── gke/         # Standard cluster + Workload Identity + private nodes
│   ├── cloudsql/    # Postgres 16 + pgvector, private IP via PSA
│   ├── memorystore/ # Redis 7 with TLS + AUTH
│   ├── gcs/         # documents (versioned) + audit (locked retention 7y)
│   ├── secrets/     # Secret Manager (api / worker / frontend)
│   └── iam/         # Workload Identity bindings + GCS + Secret Manager grants
└── environments/
    └── dev/         # Live GCP dev wiring
```

## AWS ↔ GCP equivalence map

| AWS resource | GCP resource |
|---|---|
| VPC + private subnets + NAT | VPC + subnet + Cloud NAT + PSA |
| EKS | GKE Standard, private nodes |
| IRSA (OIDC IAM trust) | Workload Identity (`<project>.svc.id.goog`) |
| RDS Postgres 16 + pgvector | Cloud SQL Postgres 16 + pgvector |
| ElastiCache Redis 7 | Memorystore Redis 7 |
| S3 + Object Lock COMPLIANCE | GCS + locked retention policy |
| Secrets Manager | Secret Manager |
| ALB Ingress | GCE Ingress (HTTPS LB) |

## Bootstrap

1. Create a GCS bucket for tfstate with versioning enabled (one-time, manual).
2. `cp environments/dev/terraform.tfvars.example environments/dev/terraform.tfvars`,
   set `project_id` + `cloudsql_master_password`.
3. `cd environments/dev && terraform init -backend-config="bucket=sentinelrag-tfstate-<project>"`
4. Enable required APIs:
   ```
   gcloud services enable container.googleapis.com sqladmin.googleapis.com \
       redis.googleapis.com secretmanager.googleapis.com \
       servicenetworking.googleapis.com compute.googleapis.com \
       --project=<project>
   ```
5. `terraform plan -out tf.plan && terraform apply tf.plan`
6. Run `terraform output kubectl_config_command` and execute it.
7. Install cluster bootstrap charts (Phase 7 Slice 3): ArgoCD, ESO,
   Temporal, cert-manager.
8. Edit `infra/helm/sentinelrag/values-gcp-dev.yaml` — replace
   `PLACEHOLDER-PROJECT` in the `iam.gke.io/gcp-service-account` annotations
   with the GSA emails from `terraform output wi_gsa_emails`.
9. `helm install sentinelrag-dev ../../helm/sentinelrag -f ../../helm/sentinelrag/values-gcp-dev.yaml`.

## What this provisions (dev)

| Resource | Choice | Module |
|---|---|---|
| VPC | 10.30.0.0/20 + secondary ranges for pods/services | `vpc` |
| GKE | Standard, private nodes, public master, e2-standard-4 × 1-3 | `gke` |
| Cloud SQL | Postgres 16, db-custom-2-4096, ZONAL, gp3 50 GB autoresize | `cloudsql` |
| Memorystore | Redis 7.2, BASIC tier, 1 GB | `memorystore` |
| GCS | `<prefix>-documents` (versioned) + `<prefix>-audit` (retention 7y, lock OFF in dev) | `gcs` |
| Secret Manager | `<release>-api`, `<release>-temporal-worker`, `<release>-frontend` | `secrets` |
| Workload Identity | api / worker / frontend / eso GSAs + KSA bindings | `iam` |

Cost note: dev defaults run around $250–$350/mo at idle on GCP.

## Notes

- `audit_lock_retention` is **off** in dev (`false`). In prod, set to `true`
  — once locked, the retention policy cannot be reduced or removed even by
  project owners. This implements ADR-0016 audit immutability.
- Cluster `deletion_protection` and Cloud SQL `deletion_protection` are
  both `false` in dev; `true` in prod.
- Memorystore on the BASIC tier has no replicas — use STANDARD_HA in prod.
