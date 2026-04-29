# Cluster bootstrap runbook

How to install the upstream Helm charts that the SentinelRAG application chart
depends on. This runbook is **shared** between AWS and GCP — the only
per-cloud differences are flagged inline (Ingress class, IRSA-vs-Workload-Identity
annotations, ClusterSecretStore manifest).

> **Read this once per cluster, in order.** Out-of-order applies will fail
> webhook handshakes and you will spend an hour debugging.
>
> If you're following the cloud-specific deploy guide, that guide will
> cross-reference each step here at the right moment.

The values overlays for every chart in this runbook live at
`infra/bootstrap/<chart>/`. ADR-0030 explains why these are committed as
plain values files rather than wrapped in a meta-chart.

---

## Prerequisites

- A live K8s cluster you can reach (`kubectl cluster-info` returns a URL).
- `helm` ≥ 3.14, `kubectl` matching the cluster's minor version, `aws` /
  `gcloud` CLI (per cloud).
- Terraform outputs from the relevant cloud (you'll paste IRSA / WI ARNs
  into bootstrap values).
- Access to the repo at this commit so the values files in
  `infra/bootstrap/` are visible.

## Order of operations

The order matters because each layer's webhook needs the previous layer's
issuer or controller. Skipping ahead causes ApiVersion-not-found or
webhook-not-ready errors.

```
1. cert-manager
2. AWS Load Balancer Controller       (AWS only)
3. External Secrets Operator + ClusterSecretStore
4. Temporal
5. ArgoCD
6. ArgoCD Application (sentinelrag-{aws,gcp}-dev)
[optional]
7. Chaos Mesh
8. Observability stack (otel collector, Tempo, Prom, Loki)
```

---

## 1. cert-manager

Installs the controller + the CRDs. Same on AWS and GCP.

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.16.2 \
  -f infra/bootstrap/cert-manager/values.yaml \
  --wait --timeout 5m

# Smoke: every pod Running, CRDs registered.
kubectl -n cert-manager get pods
kubectl get crd | grep cert-manager
```

**Add a ClusterIssuer** for Let's Encrypt before requesting any certificate:

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@sentinelrag.example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: alb     # AWS — set to "gce" on GCP overlay
EOF
```

GCP-only: when using GCE Ingress + ManagedCertificate, you can skip the
ClusterIssuer above — `networking.gke.io/managed-certificates` annotation
on the chart's Ingress handles cert provisioning. The chart's
`values-gcp-dev.yaml` already does this.

---

## 2. AWS Load Balancer Controller _(AWS only)_

Skip this on GCP — GCE Ingress is built into GKE.

```bash
helm repo add eks https://aws.github.io/eks-charts
helm repo update

# Edit infra/bootstrap/aws-load-balancer-controller/values.yaml first to
# stamp the IRSA role ARN that Terraform output:
#   terraform output -raw alb_controller_role_arn

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --version 1.10.1 \
  -f infra/bootstrap/aws-load-balancer-controller/values.yaml \
  --set clusterName=sentinelrag-dev \
  --wait --timeout 5m

# Smoke: controller pod is Running and IngressClass `alb` exists.
kubectl -n kube-system get pods -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl get ingressclass alb
```

---

## 3. External Secrets Operator + ClusterSecretStore

ESO is cloud-agnostic; the ClusterSecretStore is per-cloud.

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

# Edit infra/bootstrap/external-secrets/values.yaml first:
#   AWS:  replace eks.amazonaws.com/role-arn with terraform output -raw eso_role_arn
#   GCP:  swap the annotation to iam.gke.io/gcp-service-account: <eso GSA email>

helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets --create-namespace \
  --version 0.10.7 \
  -f infra/bootstrap/external-secrets/values.yaml \
  --wait --timeout 5m

# Smoke: 3 pods Running.
kubectl -n external-secrets get pods
```

Then apply the ClusterSecretStore for your cloud:

**AWS:**
```bash
kubectl apply -f infra/bootstrap/external-secrets/secret-store-aws.yaml
kubectl get clustersecretstore sentinelrag-aws-secrets -o jsonpath='{.status.conditions[0].status}'   # → True
```

**GCP:** edit `infra/bootstrap/external-secrets/secret-store-gcp.yaml` to set `projectID`, then apply:
```bash
kubectl apply -f infra/bootstrap/external-secrets/secret-store-gcp.yaml
kubectl get clustersecretstore sentinelrag-gcp-secrets -o jsonpath='{.status.conditions[0].status}'   # → True
```

---

## 4. Temporal

Same chart, same values, both clouds. The chart brings up its own bundled
Postgres in dev. For prod, edit
`infra/bootstrap/temporal/values.yaml` to point at a dedicated RDS / Cloud SQL
instance.

```bash
helm repo add temporal https://go.temporal.io/helm-charts
helm repo update

helm upgrade --install temporal temporal/temporal \
  --namespace temporal --create-namespace \
  --version 0.55.0 \
  -f infra/bootstrap/temporal/values.yaml \
  --wait --timeout 10m   # schema setup takes a few minutes

# Smoke: frontend reachable from inside the cluster on port 7233.
kubectl -n temporal port-forward svc/temporal-frontend 7233:7233 &
tctl --address localhost:7233 namespace list   # → "default"
kill %1
```

If `tctl` isn't installed locally, just confirm:
```bash
kubectl -n temporal get pods
```
…all pods Running.

---

## 5. ArgoCD

Installed last so it can manage everything else from then on.

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# One-time: create the Keycloak SSO client secret as a K8s Secret.
# This is referenced by infra/bootstrap/argocd/values.yaml:
#   $oidc.keycloak.clientSecret -> secret 'argocd-secret' key 'oidc.keycloak.clientSecret'
kubectl create namespace argocd
kubectl -n argocd create secret generic argocd-secret \
  --from-literal=oidc.keycloak.clientSecret="$KEYCLOAK_ARGOCD_CLIENT_SECRET"

helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --version 7.7.5 \
  -f infra/bootstrap/argocd/values.yaml \
  --wait --timeout 10m

# Surface the initial admin password for break-glass — rotate immediately
# after first SSO login.
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

Hit the UI at `https://argocd.dev.sentinelrag.example.com` once DNS
propagates. Sign in via Keycloak.

---

## 6. ArgoCD Application — SentinelRAG

The Application points ArgoCD at this repo + the right values overlay.
Apply once; ArgoCD reconciles every commit from then on.

**AWS:**
```bash
kubectl apply -f infra/bootstrap/argocd/applications/sentinelrag-dev.yaml
```

**GCP:**
```bash
kubectl apply -f infra/bootstrap/argocd/applications/sentinelrag-gcp-dev.yaml
```

Watch the first sync:
```bash
kubectl -n argocd get application sentinelrag-dev -w
# Or: open the ArgoCD UI and watch the tree resolve from "OutOfSync" → "Synced" + "Healthy".
```

---

## 7. Chaos Mesh _(optional — Phase 8 Slice 3)_

Install only when you intend to run the chaos game-day workflow. Production
clusters should not have Chaos Mesh long-term.

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update

helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh --create-namespace \
  --version 2.7.2 \
  -f infra/bootstrap/chaos-mesh/values.yaml \
  --wait --timeout 5m

# Apply the SentinelRAG chaos namespace + experiments (Phase 8).
kubectl apply -f infra/chaos/namespace.yaml
```

The experiments themselves are kept un-applied — apply when running a
game-day, then `kubectl delete` afterwards. See `infra/chaos/README.md`.

---

## 8. Observability stack _(deferred to Phase 9 polish)_

The SentinelRAG chart already emits OTLP to
`otel-collector.observability.svc.cluster.local:4318`. The collector +
Tempo + Prometheus + Loki are not yet committed as values overlays in this
directory; on Phase 9 polish completion they will land at
`infra/bootstrap/observability/values.yaml`. Until then, follow the
upstream OpenTelemetry Operator Helm chart docs:
<https://github.com/open-telemetry/opentelemetry-helm-charts>.

---

## Verification — the bootstrap stack is up

After all steps above:

```bash
# Every controller / operator namespace has Running pods.
for ns in cert-manager kube-system external-secrets temporal argocd; do
  echo "=== $ns ==="
  kubectl -n $ns get pods
done

# The ClusterSecretStore is Ready.
kubectl get clustersecretstore -A

# ArgoCD has applied SentinelRAG.
kubectl -n sentinelrag get pods
kubectl -n sentinelrag get ingress
```

If any of these are not green, **stop and fix before deploying** — the
SentinelRAG chart will fail a sync if a prerequisite isn't healthy.

---

## Bumping a chart version

This is a **deliberate operator action**. The procedure:

1. Read the upstream chart's release notes for breaking changes (CRDs,
   value renames).
2. Update the pinned version in the relevant `helm install` command in this
   runbook.
3. Apply against a staging cluster first if one exists.
4. `helm upgrade --install --diff` (the helm-diff plugin is your friend) to
   preview rendered changes.
5. Apply.
6. Re-run the verification step above.

Pinned versions and the full chart matrix live in
`infra/bootstrap/README.md`.

---

## Cross-references

- ADR-0012 — Helm + ArgoCD GitOps (the governing decision)
- ADR-0023 — Helm chart shape (why the bootstrap charts are NOT sub-charts)
- ADR-0030 — Cluster bootstrap pattern (this runbook's design choices)
- `docs/operations/runbooks/deployment-aws.md` — full end-to-end AWS deploy that uses this runbook
- `docs/operations/runbooks/deployment-gcp.md` — full end-to-end GCP deploy that uses this runbook
