# AWS deployment runbook

End-to-end procedure to take SentinelRAG from a fresh AWS account to a
live URL serving a `/query` request.

> **Read the whole runbook before starting.** Some steps wait on AWS
> resources to converge (EKS cluster takes ~15 min, RDS instance ~10 min,
> ACM cert validation depends on DNS). Plan for ~90 minutes uninterrupted.
>
> Cost note: the dev defaults below run around $200-$300/mo at idle. The
> tear-down section at the end describes how to spin them down.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| AWS CLI | ≥ 2.15 | `aws configure` against an account with admin scope (one-time bootstrap). |
| Terraform | ≥ 1.7 | `terraform -version` |
| kubectl | matching EKS minor | `kubectl version --client` |
| Helm | ≥ 3.14 | `helm version --short` |
| jq | recent | for parsing `terraform output -json` |
| Domain | yours | something you control DNS for, e.g. `sentinelrag.example.com`. |
| GHCR images published | yes | `.github/workflows/build-images.yml` must have pushed at least one `:vX.Y.Z` tag — see step 4 below. |

The IAM principal you `aws configure` against needs admin during initial
provisioning. Once the cluster + IRSA roles exist, downscope to the
`sentinelrag-*` roles for day-2 operations.

## Architecture this provisions

See [`docs/architecture/c4/L4-deployment-aws.md`](../../architecture/c4/L4-deployment-aws.md)
for the visual. Briefly:

- VPC `10.20.0.0/16`, 3 AZ public + private subnets, single NAT (dev cost saver)
- EKS 1.30 with managed node group `t3.large × 2-6`, IRSA OIDC provider
- RDS Postgres 16.4 `db.t4g.medium`, 50 GB gp3 with autoscale to 200 GB
- ElastiCache Redis 7.1 `cache.t4g.small`, single shard
- S3 `sentinelrag-dev-documents` (versioned) + `sentinelrag-dev-audit` (Object Lock COMPLIANCE 7y)
- Secrets Manager: `sentinelrag-dev/api`, `/temporal-worker`, `/frontend`
- IAM IRSA roles: `sentinelrag-dev-{api,worker,frontend,eso,alb-controller}`

OpenSearch is in the chart but **not** wired into `environments/dev/main.tf`
by default (gated behind a feature flag per ADR-0026 — opt in below).

---

## Step 1 — Bootstrap remote state (one-time per account)

Terraform's S3 backend bucket + DynamoDB lock table must exist BEFORE
`terraform init`. We create them by hand (chicken-and-egg).

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
STATE_BUCKET="sentinelrag-tfstate-${ACCOUNT_ID}"
LOCK_TABLE="sentinelrag-tfstate-locks"

aws s3api create-bucket \
  --bucket "$STATE_BUCKET" \
  --region "$REGION"

aws s3api put-bucket-versioning \
  --bucket "$STATE_BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "$STATE_BUCKET" \
  --server-side-encryption-configuration '{
    "Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]
  }'

aws s3api put-public-access-block \
  --bucket "$STATE_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws dynamodb create-table \
  --table-name "$LOCK_TABLE" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema       AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$REGION"
```

Wait until DynamoDB returns `TableStatus = ACTIVE`:
```bash
aws dynamodb wait table-exists --table-name "$LOCK_TABLE"
```

## Step 2 — Apply Terraform

```bash
cd infra/terraform/aws/environments/dev

# Create your tfvars file (gitignored).
cp terraform.tfvars.example terraform.tfvars
# Fill in:
#   region                  = "us-east-1"
#   name_prefix             = "sentinelrag-dev"
#   rds_master_password     = "$(openssl rand -base64 32)"
#   redis_auth_token        = "$(openssl rand -base64 32)"

terraform init \
  -backend-config="bucket=${STATE_BUCKET}" \
  -backend-config="dynamodb_table=${LOCK_TABLE}" \
  -backend-config="region=${REGION}"

terraform plan -out tf.plan
terraform apply tf.plan
```

Apply takes ~15 minutes (EKS dominates). When it returns:

```bash
terraform output
# Capture for later steps:
terraform output -raw kubectl_config_command   # the aws eks update-kubeconfig one-liner
terraform output -json irsa_role_arns          # ARNs to paste into bootstrap values
terraform output -raw documents_bucket
terraform output -raw audit_bucket
terraform output -raw rds_endpoint
terraform output -raw redis_endpoint
```

## Step 3 — Wire kubectl

```bash
$(terraform output -raw kubectl_config_command)
kubectl get nodes   # should show 2 t3.large nodes Ready
```

## Step 4 — Publish container images to GHCR

If this is the first deployment, you need at least one `:vX.Y.Z` tag pushed.
The CI workflow at `.github/workflows/build-images.yml` does this on tag
push. To trigger it:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Wait for the workflow to finish (~10 minutes for all three images on
linux/amd64). Verify in GHCR:
- `ghcr.io/<your-org>/sentinelrag-api:v0.1.0`
- `ghcr.io/<your-org>/sentinelrag-temporal-worker:v0.1.0`
- `ghcr.io/<your-org>/sentinelrag-frontend:v0.1.0`

If your repo is private, GHCR images are private by default. Either:
- make them public (Settings → Packages → … → Change visibility), or
- create a GHCR pull secret in the cluster (see ADR-0023's
  `imagePullSecrets` value).

## Step 5 — DNS + ACM

Create the ACM cert in the same region as the EKS cluster:

```bash
aws acm request-certificate \
  --domain-name sentinelrag.example.com \
  --subject-alternative-names "*.dev.sentinelrag.example.com" \
  --validation-method DNS \
  --region "$REGION"

# Get the validation CNAME records and create them at your DNS provider.
aws acm describe-certificate --certificate-arn <arn> \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord'
```

After validation succeeds (`Status: ISSUED`), point the DNS A/AAAA records
for `api.dev.sentinelrag.example.com` and `app.dev.sentinelrag.example.com`
at the ALB hostnames that Step 6 will produce. (Skip this step's DNS records
until the bootstrap creates the ALBs.)

## Step 6 — Bootstrap the cluster

Follow [`cluster-bootstrap.md`](cluster-bootstrap.md) end-to-end. In order:

1. cert-manager (5 min)
2. AWS Load Balancer Controller (5 min) — paste
   `terraform output -json irsa_role_arns | jq -r .alb_controller`
   (or whatever name you used) into
   `infra/bootstrap/aws-load-balancer-controller/values.yaml`
3. External Secrets Operator + `secret-store-aws.yaml` (5 min) — paste
   the ESO IRSA role ARN into the values.
4. Temporal (10 min) — bundled Postgres for dev.
5. ArgoCD (10 min) — create the Keycloak SSO client secret first.
6. Apply `infra/bootstrap/argocd/applications/sentinelrag-dev.yaml`.

## Step 7 — Update Helm values with the IRSA ARNs

`infra/helm/sentinelrag/values-dev.yaml` carries placeholder ARNs
(`arn:aws:iam::000000000000:role/sentinelrag-dev-api` etc.). Replace them
with the real ARNs from Terraform:

```bash
cd infra/helm/sentinelrag

# Get the real ARNs.
ARNS=$(cd ../../terraform/aws/environments/dev && terraform output -json irsa_role_arns)
API_ARN=$(echo "$ARNS"      | jq -r .api)
WORKER_ARN=$(echo "$ARNS"   | jq -r .worker)
FRONTEND_ARN=$(echo "$ARNS" | jq -r .frontend)

sed -i -E "s|arn:aws:iam::[0-9]+:role/sentinelrag-dev-api|${API_ARN}|"           values-dev.yaml
sed -i -E "s|arn:aws:iam::[0-9]+:role/sentinelrag-dev-worker|${WORKER_ARN}|"     values-dev.yaml
sed -i -E "s|arn:aws:iam::[0-9]+:role/sentinelrag-dev-frontend|${FRONTEND_ARN}|" values-dev.yaml || true
```

Commit + push the change. ArgoCD picks it up within 3 minutes (auto-sync).

## Step 8 — Seed Secrets Manager

Terraform created the Secrets Manager secrets but stamped placeholder
JSON values. Replace them with the real upstream values:

```bash
cd infra/terraform/aws/environments/dev

# DATABASE_URL is the only one you derive from Terraform; everything else
# you set by hand.
DB_URL="postgresql+asyncpg://$(terraform output -raw rds_username):$(terraform output -raw rds_master_password)@$(terraform output -raw rds_endpoint):5432/$(terraform output -raw rds_database_name)"
REDIS_URL="rediss://:$(terraform output -raw redis_auth_token)@$(terraform output -raw redis_endpoint):6379/0"

aws secretsmanager update-secret \
  --secret-id sentinelrag-dev/api \
  --secret-string "$(jq -n \
    --arg DATABASE_URL              "$DB_URL" \
    --arg REDIS_URL                 "$REDIS_URL" \
    --arg KEYCLOAK_ISSUER_URL       "https://auth.dev.sentinelrag.example.com/realms/sentinelrag" \
    --arg KEYCLOAK_AUDIENCE         "sentinelrag-api" \
    --arg KEYCLOAK_JWKS_URL         "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/certs" \
    --arg OBJECT_STORAGE_ACCESS_KEY "" \
    --arg OBJECT_STORAGE_SECRET_KEY "" \
    --arg UNLEASH_API_TOKEN         "<your-unleash-token>" \
    '{DATABASE_URL:$DATABASE_URL, REDIS_URL:$REDIS_URL, KEYCLOAK_ISSUER_URL:$KEYCLOAK_ISSUER_URL, KEYCLOAK_AUDIENCE:$KEYCLOAK_AUDIENCE, KEYCLOAK_JWKS_URL:$KEYCLOAK_JWKS_URL, OBJECT_STORAGE_ACCESS_KEY:$OBJECT_STORAGE_ACCESS_KEY, OBJECT_STORAGE_SECRET_KEY:$OBJECT_STORAGE_SECRET_KEY, UNLEASH_API_TOKEN:$UNLEASH_API_TOKEN})"
```

Repeat the same shape for `sentinelrag-dev/temporal-worker` and
`sentinelrag-dev/frontend` (each has a smaller key set; see
`infra/terraform/aws/environments/dev/main.tf` `module "secrets"`).

ESO refreshes in `refreshInterval` (1 h default). Force an immediate sync:
```bash
kubectl -n sentinelrag annotate externalsecret sentinelrag-api-secrets force-sync=$(date +%s) --overwrite
kubectl -n sentinelrag annotate externalsecret sentinelrag-worker-secrets force-sync=$(date +%s) --overwrite
kubectl -n sentinelrag annotate externalsecret sentinelrag-frontend-secrets force-sync=$(date +%s) --overwrite
```

## Step 9 — Watch the first sync converge

```bash
kubectl -n argocd get application sentinelrag-dev -w
# In another terminal, watch the workload pods come up.
kubectl -n sentinelrag get pods -w
```

Expected order:
1. Pre-upgrade migration Job — `alembic upgrade head` against RDS. Should
   finish in 30-60 seconds. Watch with `kubectl -n sentinelrag logs -f job/<name>`.
2. api / worker / frontend Deployments — Pods Running, Readiness probes pass.
3. Ingresses — ALB resources provisioned (takes ~3-5 min for ALB+target
   group attachment).

## Step 10 — Point DNS at the ALB

```bash
kubectl -n sentinelrag get ingress
# Copy the ADDRESS for each:
#   sentinelrag-dev-api      -> api.dev.sentinelrag.example.com
#   sentinelrag-dev-frontend -> app.dev.sentinelrag.example.com
```

Create A/AAAA records (or CNAME if your DNS supports CNAME at apex) at
your DNS provider pointing at those ALB hostnames. Propagation typically
takes 1-5 minutes; ACM serves the cert as soon as the ALB picks the right
listener rule.

## Step 11 — Smoke test

```bash
# Mint a Keycloak access token (or use the dev token if you've enabled it
# locally — but never against the deployed env).
TOKEN=$(curl -s -X POST \
  -d "grant_type=password&client_id=sentinelrag-frontend&username=demo-admin&password=$DEMO_PASSWORD" \
  "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/token" \
  | jq -r .access_token)

# Health check.
curl -fsS "https://api.dev.sentinelrag.example.com/api/v1/health"

# A query (after seeding documents — see scripts/seed/).
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"How does RBAC work?","collection_ids":["<uuid>"]}' \
  "https://api.dev.sentinelrag.example.com/api/v1/query"
```

## Step 12 — Enable the daily backup verifier (optional)

The DR backup-verify workflow no-ops by default. Enable it for this
environment:

```
GitHub repo → Settings → Variables (Actions):
  SENTINELRAG_AWS_ENABLED   = true
  SENTINELRAG_ENV           = dev
  SENTINELRAG_PREFIX        = sentinelrag-dev
  AWS_REGION                = us-east-1

GitHub repo → Settings → Secrets:
  AWS_DR_VERIFY_ROLE_ARN    = <IAM role ARN that allows describe-db-snapshots, head-bucket, etc.>
  SLACK_WEBHOOK             = <optional>
```

The role ARN is created by Terraform if you uncomment the
`aws_iam_role.dr_verify` block in `iam/main.tf` (deferred default; opt in
once the deployment is real).

---

## OpenSearch — opt in (Phase 8 reintroduction)

OpenSearch is intentionally not wired into the default `environments/dev/main.tf`.
To enable:

1. Add a `module "opensearch"` block calling `../../modules/opensearch`
   with the master password from a new tfvar.
2. `terraform apply` — provisions a 2-node domain in private subnets.
3. Update `infra/helm/sentinelrag/values-dev.yaml` to enable the
   OpenSearch keyword backend (Unleash flag `keyword_backend=opensearch`).
4. Run an indexing backfill — the worker's
   `index_chunks_to_opensearch` activity catches up on the next ingestion;
   for existing chunks, run the backfill script (Phase 9 follow-up).

Cost: ~$300+/mo on the smallest viable AWS managed OpenSearch domain.

---

## Tear down

The dev environment is destroyable. Order matters because some resources
depend on others (the audit bucket cannot be deleted without lifting
Object Lock, which is impossible during retention — that bucket must be
left behind, or the whole project re-created).

```bash
# 1. Delete the SentinelRAG ArgoCD Application — drains workloads cleanly.
kubectl -n argocd delete application sentinelrag-dev

# 2. Wait until the namespace is empty.
kubectl -n sentinelrag get all   # → No resources found

# 3. (Optional) Uninstall the bootstrap charts.
helm uninstall argocd        --namespace argocd
helm uninstall temporal      --namespace temporal
helm uninstall external-secrets --namespace external-secrets
helm uninstall aws-load-balancer-controller --namespace kube-system
helm uninstall cert-manager  --namespace cert-manager

# 4. Terraform destroy — will FAIL on the audit bucket. That's expected.
cd infra/terraform/aws/environments/dev
terraform destroy
# Read the error: "BucketNotEmpty" or "OperationAborted: Object Lock"
# The audit bucket survives (intentional). Everything else dies.
```

To delete the audit bucket too, you must wait out the 7-year retention or
permanently destroy the AWS account. Object Lock COMPLIANCE cannot be
overridden by root. This is the guarantee, not a bug. (See ADR-0016.)

---

## Cross-references

- [`docs/operations/runbooks/cluster-bootstrap.md`](cluster-bootstrap.md) — the in-cluster bootstrap stack
- [`docs/operations/runbooks/disaster-recovery.md`](disaster-recovery.md) — recovery once you're live
- [`docs/operations/runbooks/deployment-gcp.md`](deployment-gcp.md) — the GCP mirror procedure
- [`infra/terraform/aws/README.md`](../../../infra/terraform/aws/README.md) — module-by-module reference
- ADR-0011 — multi-cloud strategy
- ADR-0012 — Helm + ArgoCD GitOps
- ADR-0028 — DR commitments
