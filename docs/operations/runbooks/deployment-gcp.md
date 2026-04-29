# GCP deployment runbook

End-to-end procedure to take SentinelRAG from a fresh GCP project to a
live URL serving a `/query` request. This is the mirror of
[`deployment-aws.md`](deployment-aws.md) — same chart, same workloads,
GCP-native infrastructure underneath.

> **Read the whole runbook before starting.** GKE creation takes ~10 min,
> Cloud SQL ~10 min, ManagedCertificate validation depends on DNS. Plan
> for ~75 minutes uninterrupted.
>
> Cost: dev defaults run around $250-$350/mo at idle.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| gcloud SDK | recent | `gcloud auth login` + `gcloud auth application-default login` |
| Terraform | ≥ 1.7 | `terraform -version` |
| kubectl | matching GKE minor | `kubectl version --client` |
| Helm | ≥ 3.14 | `helm version --short` |
| jq | recent | parsing `terraform output -json` |
| Domain | yours | something you control DNS for |
| GHCR images | published | see Step 4 — same as AWS runbook |

The principal you `gcloud auth login` against needs `roles/owner` (or
equivalent compound roles) during initial provisioning.

## Architecture this provisions

See [`docs/architecture/c4/L4-deployment-gcp.md`](../../architecture/c4/L4-deployment-gcp.md)
for the visual. Briefly:

- VPC `10.30.0.0/20` + secondary ranges for GKE pods/services, Cloud NAT, PSA peering
- GKE Standard 1.30, private nodes + public master, `e2-standard-4 × 1-3`, Workload Identity
- Cloud SQL Postgres 16 `db-custom-2-4096`, ZONAL availability (REGIONAL in prod)
- Memorystore Redis 7.2 BASIC tier, 1 GB
- GCS `sentinelrag-dev-documents` (versioned) + `sentinelrag-dev-audit` (locked retention 7y)
- Secret Manager: `sentinelrag-dev-api`, `-temporal-worker`, `-frontend`
- Workload Identity: `sentinelrag-dev-{api,worker,frontend,eso,node}@<project>.iam.gserviceaccount.com`

---

## Step 1 — Create the project + enable APIs

```bash
PROJECT=sentinelrag-dev-PLACEHOLDER
REGION=us-central1
gcloud projects create "$PROJECT" --name="SentinelRAG dev"
gcloud config set project "$PROJECT"

# Link a billing account (replace BILLING_ID).
gcloud beta billing projects link "$PROJECT" --billing-account=BILLING_ID

# Enable the APIs Terraform needs.
gcloud services enable \
  compute.googleapis.com \
  container.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  secretmanager.googleapis.com \
  servicenetworking.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  artifactregistry.googleapis.com \
  certificatemanager.googleapis.com \
  --project="$PROJECT"
```

## Step 2 — Bootstrap remote state (one-time per project)

Terraform's GCS backend bucket must exist before `terraform init`.

```bash
STATE_BUCKET="sentinelrag-tfstate-${PROJECT}"
gcloud storage buckets create "gs://${STATE_BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --project="$PROJECT"

gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning
```

## Step 3 — Apply Terraform

```bash
cd infra/terraform/gcp/environments/dev

cp terraform.tfvars.example terraform.tfvars
# Fill in:
#   project_id              = "<your project>"
#   region                  = "us-central1"
#   name_prefix             = "sentinelrag-dev"
#   cloudsql_master_password = "$(openssl rand -base64 32)"

terraform init -backend-config="bucket=${STATE_BUCKET}"
terraform plan -out tf.plan
terraform apply tf.plan
```

Apply takes ~12 minutes (GKE + Cloud SQL dominate).

```bash
terraform output
# Capture for later steps:
terraform output -raw kubectl_config_command   # gcloud container clusters get-credentials ...
terraform output -json wi_gsa_emails           # Workload Identity emails for the chart values
terraform output -raw documents_bucket
terraform output -raw audit_bucket
terraform output -raw cloudsql_private_ip
terraform output -raw redis_host
```

## Step 4 — Wire kubectl

```bash
$(terraform output -raw kubectl_config_command)
kubectl get nodes   # 1-3 e2-standard-4 nodes Ready
```

## Step 5 — Publish container images to GHCR

Same as the AWS runbook — push a `vX.Y.Z` git tag to trigger
`.github/workflows/build-images.yml`.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Images land at:
- `ghcr.io/<your-org>/sentinelrag-api:v0.1.0`
- `ghcr.io/<your-org>/sentinelrag-temporal-worker:v0.1.0`
- `ghcr.io/<your-org>/sentinelrag-frontend:v0.1.0`

GKE pulls from GHCR with no extra config when images are public; for
private GHCR images, create a docker-registry pull secret in the
`sentinelrag` namespace and reference it via the chart's
`image.pullSecrets` value.

## Step 6 — DNS + ManagedCertificate

GCE Ingress provisions the cert via the `networking.gke.io/managed-certificates`
annotation (no cert-manager round-trip needed). Reserve global static IPs
that the chart references:

```bash
gcloud compute addresses create sentinelrag-dev-api \
  --global --project="$PROJECT"
gcloud compute addresses create sentinelrag-dev-app \
  --global --project="$PROJECT"

# Surface the IPs.
gcloud compute addresses list --global --filter='name~sentinelrag-dev'
```

Create A/AAAA records at your DNS provider:
- `api.dev.sentinelrag.example.com` → `sentinelrag-dev-api` IP
- `app.dev.sentinelrag.example.com` → `sentinelrag-dev-app` IP

The ManagedCertificate resources will be created by the chart in Step 9
(below), and Google will validate via DNS-01 once the records propagate.

## Step 7 — Bootstrap the cluster

Follow [`cluster-bootstrap.md`](cluster-bootstrap.md), with these GCP
adjustments:

1. **cert-manager** — same. Skip the `letsencrypt-prod` ClusterIssuer if you
   only use ManagedCertificate (recommended).
2. **AWS Load Balancer Controller** — **skip**, GCE Ingress is built in.
3. **External Secrets Operator + secret-store-gcp.yaml** — edit
   `infra/bootstrap/external-secrets/values.yaml`:
   - Comment out the `eks.amazonaws.com/role-arn` annotation.
   - Uncomment / add the `iam.gke.io/gcp-service-account` annotation,
     using the value from `terraform output -json wi_gsa_emails | jq -r .eso`.
   - Apply, then edit `secret-store-gcp.yaml` to set `projectID`, then apply.
4. **Temporal** — same.
5. **ArgoCD** — same. Set the Ingress class to `gce` in
   `infra/bootstrap/argocd/values.yaml` and adjust the annotations to
   `kubernetes.io/ingress.global-static-ip-name` +
   `networking.gke.io/managed-certificates`.
6. Apply `infra/bootstrap/argocd/applications/sentinelrag-gcp-dev.yaml`.

## Step 8 — Update Helm values with the Workload Identity emails

`infra/helm/sentinelrag/values-gcp-dev.yaml` carries placeholder GSA
emails (`sentinelrag-dev-api@PLACEHOLDER-PROJECT.iam.gserviceaccount.com`
etc.). Replace them with the real ones:

```bash
cd infra/helm/sentinelrag

WI=$(cd ../../terraform/gcp/environments/dev && terraform output -json wi_gsa_emails)
API_GSA=$(echo "$WI"      | jq -r .api)
WORKER_GSA=$(echo "$WI"   | jq -r .worker)
FRONTEND_GSA=$(echo "$WI" | jq -r .frontend)

sed -i -E "s|sentinelrag-dev-api@PLACEHOLDER-PROJECT\.iam\.gserviceaccount\.com|${API_GSA}|"           values-gcp-dev.yaml
sed -i -E "s|sentinelrag-dev-worker@PLACEHOLDER-PROJECT\.iam\.gserviceaccount\.com|${WORKER_GSA}|"     values-gcp-dev.yaml
sed -i -E "s|sentinelrag-dev-frontend@PLACEHOLDER-PROJECT\.iam\.gserviceaccount\.com|${FRONTEND_GSA}|" values-gcp-dev.yaml
```

Commit + push. ArgoCD picks it up within 3 minutes.

## Step 9 — Seed Secret Manager

```bash
cd infra/terraform/gcp/environments/dev

DB_URL="postgresql+asyncpg://$(terraform output -raw cloudsql_username):$(terraform output -raw cloudsql_master_password)@$(terraform output -raw cloudsql_private_ip):5432/$(terraform output -raw cloudsql_database_name)"
REDIS_URL="rediss://default:$(terraform output -raw redis_auth_string)@$(terraform output -raw redis_host):$(terraform output -raw redis_port)/0"

# Update each secret. Each Secret Manager secret holds a JSON KV blob.
gcloud secrets versions add sentinelrag-dev-api --data-file=<(jq -n \
  --arg DATABASE_URL              "$DB_URL" \
  --arg REDIS_URL                 "$REDIS_URL" \
  --arg KEYCLOAK_ISSUER_URL       "https://auth.dev.sentinelrag.example.com/realms/sentinelrag" \
  --arg KEYCLOAK_AUDIENCE         "sentinelrag-api" \
  --arg KEYCLOAK_JWKS_URL         "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/certs" \
  --arg OBJECT_STORAGE_ACCESS_KEY "" \
  --arg OBJECT_STORAGE_SECRET_KEY "" \
  --arg UNLEASH_API_TOKEN         "<your-unleash-token>" \
  '{DATABASE_URL:$DATABASE_URL, REDIS_URL:$REDIS_URL, KEYCLOAK_ISSUER_URL:$KEYCLOAK_ISSUER_URL, KEYCLOAK_AUDIENCE:$KEYCLOAK_AUDIENCE, KEYCLOAK_JWKS_URL:$KEYCLOAK_JWKS_URL, OBJECT_STORAGE_ACCESS_KEY:$OBJECT_STORAGE_ACCESS_KEY, OBJECT_STORAGE_SECRET_KEY:$OBJECT_STORAGE_SECRET_KEY, UNLEASH_API_TOKEN:$UNLEASH_API_TOKEN}')
```

Repeat the same shape for `sentinelrag-dev-temporal-worker` and
`sentinelrag-dev-frontend` (smaller key sets — see
`infra/terraform/gcp/environments/dev/main.tf` `module "secrets"`).

Force ESO refresh:
```bash
kubectl -n sentinelrag annotate externalsecret sentinelrag-api-secrets force-sync=$(date +%s) --overwrite
kubectl -n sentinelrag annotate externalsecret sentinelrag-worker-secrets force-sync=$(date +%s) --overwrite
kubectl -n sentinelrag annotate externalsecret sentinelrag-frontend-secrets force-sync=$(date +%s) --overwrite
```

## Step 10 — Watch the first sync

```bash
kubectl -n argocd get application sentinelrag-gcp-dev -w
kubectl -n sentinelrag get pods -w
```

Expected order is the same as AWS:
1. Pre-upgrade migration Job
2. api / worker / frontend Pods
3. GCE Ingress provisions the LB (~5-10 min)
4. ManagedCertificate transitions from `Provisioning` → `Active` (5-30 min after DNS resolves)

```bash
kubectl -n sentinelrag get managedcertificate
```

## Step 11 — Smoke test

```bash
TOKEN=$(curl -s -X POST \
  -d "grant_type=password&client_id=sentinelrag-frontend&username=demo-admin&password=$DEMO_PASSWORD" \
  "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/token" \
  | jq -r .access_token)

curl -fsS "https://api.dev.sentinelrag.example.com/api/v1/health"

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"How does RBAC work?","collection_ids":["<uuid>"]}' \
  "https://api.dev.sentinelrag.example.com/api/v1/query"
```

## Step 12 — Enable the daily backup verifier

```
GitHub repo → Settings → Variables (Actions):
  SENTINELRAG_GCP_ENABLED   = true
  SENTINELRAG_GCP_PROJECT   = <your project>
  SENTINELRAG_ENV           = dev
  SENTINELRAG_PREFIX        = sentinelrag-dev

GitHub repo → Settings → Secrets:
  GCP_WIF_PROVIDER          = projects/<num>/locations/global/workloadIdentityPools/github/providers/sentinelrag
  GCP_DR_VERIFY_SA          = sentinelrag-dr-verify@<project>.iam.gserviceaccount.com
  SLACK_WEBHOOK             = <optional>
```

The Workload Identity Federation provider + the dr-verify SA are
operator-provisioned; not in `infra/terraform/gcp/` today (Phase 9 follow-up).

---

## Tear down

```bash
# 1. Delete the SentinelRAG ArgoCD Application.
kubectl -n argocd delete application sentinelrag-gcp-dev
kubectl -n sentinelrag get all   # → No resources found

# 2. Optionally uninstall the bootstrap charts.
helm uninstall argocd            --namespace argocd
helm uninstall temporal          --namespace temporal
helm uninstall external-secrets  --namespace external-secrets
helm uninstall cert-manager      --namespace cert-manager

# 3. Terraform destroy — fails on the audit bucket because retention is locked.
cd infra/terraform/gcp/environments/dev
terraform destroy
```

The audit bucket survives the `destroy` (locked retention policy is
non-revocable for 7 years). To delete it, you must wait out the
retention or destroy the GCP project. This is the guarantee, not a bug.

---

## Cross-references

- [`docs/operations/runbooks/cluster-bootstrap.md`](cluster-bootstrap.md) — the in-cluster bootstrap stack
- [`docs/operations/runbooks/disaster-recovery.md`](disaster-recovery.md) — recovery once you're live
- [`docs/operations/runbooks/deployment-aws.md`](deployment-aws.md) — the AWS twin
- [`infra/terraform/gcp/README.md`](../../../infra/terraform/gcp/README.md) — module-by-module reference
- ADR-0011 — multi-cloud strategy
- ADR-0025 — GCP parity
- ADR-0028 — DR commitments
