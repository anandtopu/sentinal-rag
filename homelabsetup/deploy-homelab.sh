#!/usr/bin/env bash
# ============================================================
# deploy-homelab.sh — Deploy SentinelRAG to the K3s homelab
# ============================================================
# Prerequisites:
#   - 3-node K3s cluster running (bootstrap-homelab.sh did this)
#   - kubectl points at the homelab kubeconfig
#       export KUBECONFIG=$HOME/.kube/config-sentinelrag-homelab
#   - Docker Desktop running on the build host
#   - registry.local in hosts file (or NODE1_IP reachable)
#   - Docker Desktop has registry.local:30500 in insecure-registries
#
# Usage:
#   ./homelabsetup/deploy-homelab.sh
#   ./homelabsetup/deploy-homelab.sh --skip-build      # reuse last common build tag
#   ./homelabsetup/deploy-homelab.sh --skip-models     # don't pull Ollama models
#   ./homelabsetup/deploy-homelab.sh --skip-dns        # don't print DNS hint
#   ./homelabsetup/deploy-homelab.sh --skip-mirror-check
#   ./homelabsetup/deploy-homelab.sh --teardown        # delete app (keep PVCs)
#   ./homelabsetup/deploy-homelab.sh --teardown-all    # delete + wipe data
# ============================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="registry.local:30500"
NAMESPACE="sentinelrag"
RELEASE="sentinelrag"
CHART_PATH="$REPO_ROOT/infra/helm/sentinelrag"
VALUES_FILE="$CHART_PATH/values-homelab.yaml"

NODE_USER="${NODE_USER:-labadmin}"
NODE1_IP="${NODE1_IP:-192.168.0.101}"
CONTROL_NODE="$NODE1_IP"

# Image names — must match `<workload>.image.name` in values-homelab.yaml.
IMG_API="sentinelrag-api"
IMG_RETRIEVAL="sentinelrag-retrieval-service"
IMG_WORKER="sentinelrag-temporal-worker"
IMG_FRONTEND="sentinelrag-frontend"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

# ── Flags ───────────────────────────────────────────────────
SKIP_BUILD=false
SKIP_MODELS=false
SKIP_DNS=false
SKIP_MIRROR_CHECK=false
TEARDOWN=false
TEARDOWN_ALL=false

for arg in "$@"; do
  case $arg in
    --skip-build)        SKIP_BUILD=true ;;
    --skip-models)       SKIP_MODELS=true ;;
    --skip-dns)          SKIP_DNS=true ;;
    --skip-mirror-check) SKIP_MIRROR_CHECK=true ;;
    --skip-registry)     ;; # accepted for bootstrap-handoff symmetry, no-op
    --teardown)          TEARDOWN=true ;;
    --teardown-all)      TEARDOWN_ALL=true ;;
    -h|--help)
      sed -n '2,22p' "$0"; exit 0 ;;
    *) echo -e "${RED}Unknown flag: $arg${NC}"; exit 1 ;;
  esac
done

# ── Helpers ─────────────────────────────────────────────────
log()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
error()  { echo -e "${RED}[x]${NC} $*"; exit 1; }
header() { echo -e "\n${CYAN}══════════════════════════════════════════════════${NC}"; echo -e "${CYAN}  $*${NC}"; echo -e "${CYAN}══════════════════════════════════════════════════${NC}\n"; }

check_command() {
  command -v "$1" >/dev/null 2>&1 || error "$1 is required but not installed."
}

wait_for_pods() {
  local label=$1
  local timeout=${2:-180}
  log "Waiting for pods with label $label (timeout: ${timeout}s)..."
  kubectl -n "$NAMESPACE" wait --for=condition=ready pod -l "$label" --timeout="${timeout}s" 2>/dev/null || {
    warn "Pods with label $label not ready within ${timeout}s. Status:"
    kubectl -n "$NAMESPACE" get pods -l "$label"
    return 1
  }
}

check_registry() {
  if curl -sf --max-time 5 "http://${REGISTRY}/v2/_catalog" >/dev/null 2>&1; then return 0; fi
  if curl -sf --max-time 5 "http://${CONTROL_NODE}:30500/v2/_catalog" >/dev/null 2>&1; then
    warn "registry.local not resolving — reaching registry via ${CONTROL_NODE}:30500 instead."
    return 0
  fi
  return 1
}

# ── Teardown ────────────────────────────────────────────────
if [ "$TEARDOWN_ALL" = true ]; then
  header "TEARDOWN-ALL (DESTRUCTIVE) — Delete namespace + ALL data"
  warn "This deletes the entire ${NAMESPACE} namespace, including ALL persistent volumes (Postgres, MinIO, Keycloak, Ollama models)."
  read -rp "Type 'yes' to confirm: " confirm
  [ "$confirm" = "yes" ] || { echo "Aborted."; exit 0; }
  helm -n "$NAMESPACE" uninstall "$RELEASE" --ignore-not-found 2>/dev/null || true
  kubectl delete namespace "$NAMESPACE" --ignore-not-found
  log "Namespace ${NAMESPACE} deleted."
  exit 0
fi

if [ "$TEARDOWN" = true ]; then
  header "TEARDOWN — Helm uninstall (PVCs preserved)"
  helm -n "$NAMESPACE" uninstall "$RELEASE" --ignore-not-found
  log "Release uninstalled. PVCs and data preserved in namespace ${NAMESPACE}."
  exit 0
fi

# ── Preflight ───────────────────────────────────────────────
header "Step 0 — Preflight"
check_command kubectl
check_command helm
check_command docker
check_command curl
check_command sed
check_command openssl

[ -f "$VALUES_FILE" ] || error "values-homelab.yaml not found at $VALUES_FILE"

log "Checking kubectl cluster access..."
kubectl get nodes >/dev/null 2>&1 || error "Cannot reach the cluster. Did you 'export KUBECONFIG=...'?"

NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
log "Cluster has $NODE_COUNT node(s)"

log "Checking Docker Desktop..."
docker info >/dev/null 2>&1 || error "Docker is not running. Start Docker Desktop first."

log "Checking local-path StorageClass..."
kubectl get storageclass local-path >/dev/null 2>&1 || error "local-path StorageClass not found. Is this a K3s cluster?"

log "Checking registry reachability..."
check_registry || error "Registry not reachable at http://${REGISTRY}/v2/_catalog. Run bootstrap-homelab.sh first, or check /etc/hosts + Docker Desktop insecure-registries."

# ── Pre-apply containerd mirror check ───────────────────────
if [ "$SKIP_MIRROR_CHECK" = false ]; then
  log "Pre-checking K3s containerd mirror config on every node..."
  mirror_missing_nodes=()
  for node in $(kubectl get nodes -o name 2>/dev/null | sed 's|^node/||'); do
    if ! kubectl debug "node/$node" --image=busybox:1.36 \
           --quiet --profile=sysadmin -- \
           chroot /host grep -q "registry.local:30500" \
                /etc/rancher/k3s/registries.yaml >/dev/null 2>&1; then
      mirror_missing_nodes+=("$node")
    fi
  done
  kubectl -n default delete pods -l created-by=kubectl-debug --ignore-not-found=true >/dev/null 2>&1 || true

  if [ ${#mirror_missing_nodes[@]} -gt 0 ]; then
    warn "K3s containerd mirror config is missing on these nodes:"
    for n in "${mirror_missing_nodes[@]}"; do echo "       - $n"; done
    warn "Re-run ./homelabsetup/bootstrap-homelab.sh to fix (idempotent), or pass --skip-mirror-check."
    exit 1
  fi
fi

# ── Step 1 — Resolve / build BUILD_TAG ──────────────────────
if [ "$SKIP_BUILD" = false ]; then
  BUILD_TAG="build-$(date -u +%Y%m%d-%H%M%S)"
  header "Step 1 — Build + push images (${BUILD_TAG})"

  cd "$REPO_ROOT"

  # Pick the working registry endpoint (host vs IP).
  if curl -sf --max-time 3 "http://${REGISTRY}/v2/_catalog" >/dev/null 2>&1; then
    PUSH_REGISTRY="$REGISTRY"
  else
    PUSH_REGISTRY="${CONTROL_NODE}:30500"
    warn "Falling back to IP-based registry: ${PUSH_REGISTRY}"
  fi

  log "Building ${IMG_API}:${BUILD_TAG}..."
  docker build -t "${PUSH_REGISTRY}/${IMG_API}:${BUILD_TAG}" \
    -f apps/api/Dockerfile .

  log "Building ${IMG_RETRIEVAL}:${BUILD_TAG}..."
  docker build -t "${PUSH_REGISTRY}/${IMG_RETRIEVAL}:${BUILD_TAG}" \
    -f apps/retrieval-service/Dockerfile .

  log "Building ${IMG_WORKER}:${BUILD_TAG}..."
  docker build -t "${PUSH_REGISTRY}/${IMG_WORKER}:${BUILD_TAG}" \
    -f apps/temporal-worker/Dockerfile .

  log "Building ${IMG_FRONTEND}:${BUILD_TAG}..."
  docker build --pull -t "${PUSH_REGISTRY}/${IMG_FRONTEND}:${BUILD_TAG}" \
    -f apps/frontend/Dockerfile apps/frontend/

  log "Pushing all images..."
  docker push "${PUSH_REGISTRY}/${IMG_API}:${BUILD_TAG}"
  docker push "${PUSH_REGISTRY}/${IMG_RETRIEVAL}:${BUILD_TAG}"
  docker push "${PUSH_REGISTRY}/${IMG_WORKER}:${BUILD_TAG}"
  docker push "${PUSH_REGISTRY}/${IMG_FRONTEND}:${BUILD_TAG}"

  log "Registry catalog:"
  curl -s "http://${PUSH_REGISTRY}/v2/_catalog" 2>/dev/null || warn "Could not query registry catalog"
else
  header "Step 1 — Resolve existing BUILD_TAG (--skip-build)"
  # Pick a tag that ALL four images share, so helm doesn't pin to a non-existent tag.
  if curl -sf --max-time 3 "http://${REGISTRY}/v2/_catalog" >/dev/null 2>&1; then
    LOOKUP_REGISTRY="$REGISTRY"
  else
    LOOKUP_REGISTRY="${CONTROL_NODE}:30500"
  fi

  _tags() {
    curl -sf --max-time 10 "http://${LOOKUP_REGISTRY}/v2/$1/tags/list" 2>/dev/null \
      | sed -e 's/.*"tags":\[//' -e 's/\].*//' -e 's/"//g' -e 's/,/\n/g' \
      | grep -E '^build-[0-9]{8}-[0-9]{6}$' || true
  }
  BUILD_TAG=$(comm -12 \
    <(_tags "$IMG_API" | sort -ru) \
    <(comm -12 \
      <(_tags "$IMG_RETRIEVAL" | sort -ru) \
      <(comm -12 \
        <(_tags "$IMG_WORKER" | sort -ru) \
        <(_tags "$IMG_FRONTEND" | sort -ru))) \
    | head -n 1)

  if [ -z "$BUILD_TAG" ]; then
    cat >&2 <<EOF
[!] --skip-build asked us to reuse a tag, but no build-YYYYMMDD-HHMMSS
    tag exists for ALL FOUR images at http://${LOOKUP_REGISTRY}.

    Fix: re-run without --skip-build to push fresh images.
EOF
    exit 1
  fi
  log "Resolved BUILD_TAG=${BUILD_TAG} (newest tag common to all four image catalogs)"
fi

# ── Step 2 — Create namespace ───────────────────────────────
header "Step 2 — Namespace ${NAMESPACE}"
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE"

# ── Step 3 — Secrets ────────────────────────────────────────
header "Step 3 — Application secrets"

# api / retrieval / worker / frontend each have their own Secret per
# values-homelab.yaml. We generate them once and never rotate (homelab
# isn't a security-sensitive context). Re-runs are idempotent — if the
# Secret already exists, we leave it alone.

ensure_secret() {
  local name=$1
  shift
  if kubectl -n "$NAMESPACE" get secret "$name" >/dev/null 2>&1; then
    log "Secret $name already exists. Skipping."
  else
    kubectl -n "$NAMESPACE" create secret generic "$name" "$@"
    log "Created secret $name."
  fi
}

# Postgres connection strings inside the cluster use the Bitnami service
# name: sentinelrag-postgresql.sentinelrag.svc.cluster.local:5432. The
# default user is sentinel / sentinel-homelab-change-me (per the chart).
DB_URL="postgresql+asyncpg://sentinel:sentinel-homelab-change-me@sentinelrag-postgresql.${NAMESPACE}.svc.cluster.local:5432/sentinelrag"
DB_URL_SYNC="postgresql://sentinel:sentinel-homelab-change-me@sentinelrag-postgresql.${NAMESPACE}.svc.cluster.local:5432/sentinelrag"
REDIS_URL="redis://sentinelrag-redis-master.${NAMESPACE}.svc.cluster.local:6379/0"
KEYCLOAK_ISSUER="http://auth.sentinelrag.local/realms/sentinelrag"
KEYCLOAK_JWKS="${KEYCLOAK_ISSUER}/protocol/openid-connect/certs"

# A shared token gates the API↔retrieval HTTP transport (R4.S5).
RETRIEVAL_TOKEN=$(openssl rand -hex 32)

ensure_secret sentinelrag-api-secrets \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=DATABASE_URL_SYNC="$DB_URL_SYNC" \
  --from-literal=REDIS_URL="$REDIS_URL" \
  --from-literal=KEYCLOAK_ISSUER_URL="$KEYCLOAK_ISSUER" \
  --from-literal=KEYCLOAK_AUDIENCE="sentinelrag-api" \
  --from-literal=KEYCLOAK_JWKS_URL="$KEYCLOAK_JWKS" \
  --from-literal=OBJECT_STORAGE_ACCESS_KEY="minioadmin" \
  --from-literal=OBJECT_STORAGE_SECRET_KEY="minioadmin-homelab-change-me" \
  --from-literal=UNLEASH_API_TOKEN="default:development.unleash-insecure-api-token" \
  --from-literal=RETRIEVAL_SERVICE_TOKEN="$RETRIEVAL_TOKEN"

ensure_secret sentinelrag-retrieval-secrets \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=SERVICE_TOKEN="$RETRIEVAL_TOKEN"

ensure_secret sentinelrag-worker-secrets \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=REDIS_URL="$REDIS_URL" \
  --from-literal=OBJECT_STORAGE_ACCESS_KEY="minioadmin" \
  --from-literal=OBJECT_STORAGE_SECRET_KEY="minioadmin-homelab-change-me"

# Frontend: NextAuth needs a strong session secret; KEYCLOAK_CLIENT_SECRET
# must match what the Keycloak realm export ships for the sentinelrag-frontend
# client. The realm-export.json checks in /scripts/local/keycloak/.
NEXTAUTH_SECRET=$(openssl rand -hex 32)
FRONTEND_CLIENT_SECRET="${FRONTEND_CLIENT_SECRET:-sentinelrag-frontend-homelab-secret}"

ensure_secret sentinelrag-frontend-secrets \
  --from-literal=NEXTAUTH_SECRET="$NEXTAUTH_SECRET" \
  --from-literal=KEYCLOAK_CLIENT_ID="sentinelrag-frontend" \
  --from-literal=KEYCLOAK_CLIENT_SECRET="$FRONTEND_CLIENT_SECRET"

# Keycloak realm ConfigMap (read by the keycloak subchart's extraVolumes).
REALM_EXPORT="$REPO_ROOT/scripts/local/keycloak/realm-export.json"
if [ -f "$REALM_EXPORT" ]; then
  kubectl -n "$NAMESPACE" create configmap sentinelrag-keycloak-realm \
    --from-file=realm-export.json="$REALM_EXPORT" \
    --dry-run=client -o yaml | kubectl apply -f -
  log "Keycloak realm ConfigMap applied."
else
  warn "Realm export not found at $REALM_EXPORT — Keycloak will start with an empty realm."
  warn "Login will not work until you import the realm manually via the Keycloak admin UI."
fi

# Persist creds + the BUILD_TAG to a local file (gitignored).
CREDS_FILE="$REPO_ROOT/homelabsetup/.homelab-credentials"
cat > "$CREDS_FILE" <<CREDS
# SentinelRAG Homelab Credentials — generated $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT COMMIT THIS FILE
NAMESPACE=${NAMESPACE}
RELEASE=${RELEASE}
BUILD_TAG=${BUILD_TAG}

# Database (Bitnami postgresql sub-chart in-cluster)
POSTGRES_USER=sentinel
POSTGRES_PASSWORD=sentinel-homelab-change-me
DATABASE_URL=${DB_URL}

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin-homelab-change-me

# Keycloak (sub-chart)
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=admin-homelab-change-me
KEYCLOAK_ISSUER_URL=${KEYCLOAK_ISSUER}

# Shared bearer for API ↔ retrieval HTTP transport
RETRIEVAL_SERVICE_TOKEN=${RETRIEVAL_TOKEN}

# NextAuth + Keycloak frontend client
NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
KEYCLOAK_FRONTEND_CLIENT_ID=sentinelrag-frontend
KEYCLOAK_FRONTEND_CLIENT_SECRET=${FRONTEND_CLIENT_SECRET}

# Unleash
UNLEASH_API_TOKEN=default:development.unleash-insecure-api-token

# Demo admin user (seeded by deploy banner)
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@sentinelrag.local
ADMIN_PASSWORD=Admin@2026!
CREDS
log "Credentials persisted to homelabsetup/.homelab-credentials (do NOT commit)"

# ── Step 4 — Helm dependency update ─────────────────────────
header "Step 4 — helm dependency update"

# The chart declares Bitnami subcharts + Unleash. We need them resolved
# locally before `helm upgrade --install` can use them.
helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
helm repo add unleash https://docs.getunleash.io/helm-charts >/dev/null 2>&1 || true
helm repo update bitnami unleash >/dev/null

helm dependency update "$CHART_PATH"

# ── Step 5 — helm upgrade --install ─────────────────────────
header "Step 5 — helm upgrade --install ${RELEASE} (tag=${BUILD_TAG})"

# Substitute BUILD_TAG_PLACEHOLDER in values-homelab.yaml so the rollout
# pins to this immutable tag (matches the TestLookup pattern). Trap
# restores the placeholder on success or failure so `git status` stays
# clean and re-runs work from the canonical source.
cp "$VALUES_FILE" "${VALUES_FILE}.deploy-bak"
restore_values() {
  if [ -f "${VALUES_FILE}.deploy-bak" ]; then
    mv -f "${VALUES_FILE}.deploy-bak" "$VALUES_FILE"
  fi
}
trap restore_values EXIT INT TERM

sed -i.tmp "s/BUILD_TAG_PLACEHOLDER/${BUILD_TAG}/g" "$VALUES_FILE"
rm -f "${VALUES_FILE}.tmp"

if grep -q "BUILD_TAG_PLACEHOLDER" "$VALUES_FILE"; then
  error "BUILD_TAG_PLACEHOLDER still present in values-homelab.yaml after substitution."
fi

helm upgrade --install "$RELEASE" "$CHART_PATH" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f "$VALUES_FILE" \
  --timeout 15m \
  --wait

restore_values
trap - EXIT INT TERM

# ── Step 5b — Ensure pgvector extension ─────────────────────
# Bitnami's Postgres image with `image.repository=pgvector/pgvector` ships
# the .so, but `CREATE EXTENSION vector` only runs from initdb scripts on
# first boot. If the chart was installed before pgvector was wired up, the
# extension won't exist. This Job is idempotent and cheap — always run it.
header "Step 5b — Ensure pgvector extension"
kubectl -n "$NAMESPACE" delete job sentinelrag-pgvector-ensure --ignore-not-found >/dev/null
cat <<YAML | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: sentinelrag-pgvector-ensure
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 120
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: psql
          image: pgvector/pgvector:pg16
          env:
            - name: PGPASSWORD
              value: sentinel-homelab-change-me
          command:
            - sh
            - -c
            - |
              until pg_isready -h sentinelrag-postgresql.${NAMESPACE}.svc.cluster.local -U sentinel; do
                echo "Waiting for Postgres..."; sleep 3
              done
              psql -h sentinelrag-postgresql.${NAMESPACE}.svc.cluster.local \\
                   -U sentinel -d sentinelrag \\
                   -c 'CREATE EXTENSION IF NOT EXISTS vector;'
YAML
kubectl -n "$NAMESPACE" wait --for=condition=complete --timeout=120s job/sentinelrag-pgvector-ensure || warn "pgvector ensure-job did not complete cleanly. Check: kubectl -n $NAMESPACE logs job/sentinelrag-pgvector-ensure"

# ── Step 6 — Force fresh image pull on app deployments ──────
header "Step 6 — Force fresh rollout"
APP_DEPLOYMENTS=(
  "${RELEASE}-api"
  "${RELEASE}-retrieval"
  "${RELEASE}-temporal-worker"
  "${RELEASE}-frontend"
)
for dep in "${APP_DEPLOYMENTS[@]}"; do
  if kubectl -n "$NAMESPACE" get deployment "$dep" >/dev/null 2>&1; then
    kubectl -n "$NAMESPACE" rollout restart deployment/"$dep" >/dev/null
  else
    warn "Deployment $dep not found yet — first install will create it."
  fi
done

for dep in "${APP_DEPLOYMENTS[@]}"; do
  if kubectl -n "$NAMESPACE" get deployment "$dep" >/dev/null 2>&1; then
    kubectl -n "$NAMESPACE" rollout status deployment/"$dep" --timeout=300s \
      || warn "$dep did not become ready — check kubectl -n $NAMESPACE describe deployment $dep"
  fi
done

# ── Step 7 — Pull Ollama models ─────────────────────────────
if [ "$SKIP_MODELS" = false ]; then
  header "Step 7 — Pull Ollama models"

  wait_for_pods "app=ollama" 180 || warn "Ollama pod not ready; skipping model pull."

  OLLAMA_POD=$(kubectl -n "$NAMESPACE" get pod -l app=ollama -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [ -n "$OLLAMA_POD" ]; then
    EXISTING=$(kubectl -n "$NAMESPACE" exec "$OLLAMA_POD" -- ollama list 2>/dev/null || echo "")
    if echo "$EXISTING" | grep -q "llama3.1:8b"; then
      log "llama3.1:8b already present."
    else
      log "Pulling llama3.1:8b (may take several minutes)..."
      kubectl -n "$NAMESPACE" exec "$OLLAMA_POD" -- ollama pull llama3.1:8b
    fi
    if echo "$EXISTING" | grep -q "nomic-embed-text"; then
      log "nomic-embed-text already present."
    else
      log "Pulling nomic-embed-text..."
      kubectl -n "$NAMESPACE" exec "$OLLAMA_POD" -- ollama pull nomic-embed-text
    fi
    log "Installed models:"
    kubectl -n "$NAMESPACE" exec "$OLLAMA_POD" -- ollama list
  fi
fi

# ── Step 8 — DNS hint ───────────────────────────────────────
if [ "$SKIP_DNS" = false ]; then
  header "Step 8 — DNS hint"
  TRAEFIK_IP=$(kubectl -n kube-system get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  if [ -n "$TRAEFIK_IP" ]; then
    log "Traefik external IP: $TRAEFIK_IP"
    HOSTS_FILE="/etc/hosts"
    [ -f "/c/Windows/System32/drivers/etc/hosts" ] && HOSTS_FILE="/c/Windows/System32/drivers/etc/hosts"

    HOSTS_OK=true
    for host in app.sentinelrag.local api.sentinelrag.local auth.sentinelrag.local; do
      HOSTS_LINE="$(grep -E "^[^#]*\s${host}(\s|$)" "$HOSTS_FILE" 2>/dev/null | head -1 || true)"
      HOSTS_IP="$(echo "$HOSTS_LINE" | awk '{print $1}')"
      if [ -z "$HOSTS_LINE" ]; then
        HOSTS_OK=false
        warn "${host} is missing from $HOSTS_FILE"
      elif [ "$HOSTS_IP" != "$TRAEFIK_IP" ]; then
        HOSTS_OK=false
        warn "${host} maps to ${HOSTS_IP} but Traefik is now on ${TRAEFIK_IP}"
      fi
    done

    if [ "$HOSTS_OK" = false ]; then
      echo ""
      echo "  Windows (Admin PowerShell):"
      echo "    Add-Content C:\\Windows\\System32\\drivers\\etc\\hosts \"$TRAEFIK_IP app.sentinelrag.local\""
      echo "    Add-Content C:\\Windows\\System32\\drivers\\etc\\hosts \"$TRAEFIK_IP api.sentinelrag.local\""
      echo "    Add-Content C:\\Windows\\System32\\drivers\\etc\\hosts \"$TRAEFIK_IP auth.sentinelrag.local\""
      echo "    ipconfig /flushdns"
      echo ""
      echo "  Linux/Mac:"
      echo "    sudo sh -c 'echo \"$TRAEFIK_IP app.sentinelrag.local api.sentinelrag.local auth.sentinelrag.local\" >> /etc/hosts'"
      echo ""
    else
      log "Hosts file already maps all three hostnames → ${TRAEFIK_IP} ✓"
    fi
  else
    warn "Could not determine Traefik IP. Check: kubectl -n kube-system get svc traefik"
  fi
fi

# ── Step 9 — Seed demo tenant + admin ───────────────────────
header "Step 9 — Seed demo tenant + admin"

# scripts/seed/seed_demo.py is the canonical seeder. Run it inside the API
# pod so DATABASE_URL is already in env. Idempotent at the SQL layer.
wait_for_pods "app.kubernetes.io/component=api" 240 || warn "API pod not ready; skipping seed."
API_POD=$(kubectl -n "$NAMESPACE" get pod -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$API_POD" ] && [ -f "$REPO_ROOT/scripts/seed/seed_demo.py" ]; then
  log "Running seed_demo.py inside ${API_POD}..."
  kubectl -n "$NAMESPACE" exec -i "$API_POD" -- python < "$REPO_ROOT/scripts/seed/seed_demo.py" \
    || warn "Seed script failed. Run manually: kubectl -n $NAMESPACE exec -i deploy/${RELEASE}-api -- python < scripts/seed/seed_demo.py"
fi

# ── Step 10 — Verification ──────────────────────────────────
header "Step 10 — Verification"
kubectl -n "$NAMESPACE" get pods -o wide
echo
kubectl -n "$NAMESPACE" get svc
echo
kubectl -n "$NAMESPACE" get ingress

# ── Summary ─────────────────────────────────────────────────
header "Deployment Complete"
echo -e "${GREEN}SentinelRAG is deployed to the K3s homelab.${NC}"
echo
echo "  Dashboard:  http://app.sentinelrag.local"
echo "  API docs:   http://api.sentinelrag.local/docs"
echo "  Keycloak:   http://auth.sentinelrag.local"
echo "  MinIO console (port-forward): kubectl -n ${NAMESPACE} port-forward svc/${RELEASE}-minio 9001:9001"
echo "  Temporal UI (port-forward):   kubectl -n temporal port-forward svc/temporal-web 8080:8080"
echo
echo "  Admin (Keycloak):        admin / admin-homelab-change-me"
echo "  Demo tenant admin:       admin@sentinelrag.local / Admin@2026!"
echo "  Credentials file:        homelabsetup/.homelab-credentials"
echo
echo "Update after code changes:"
echo "  $0          # rebuild + push + helm upgrade"
echo
echo "Tail logs:"
echo "  kubectl -n ${NAMESPACE} logs -f deploy/${RELEASE}-api"
