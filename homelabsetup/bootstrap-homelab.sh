#!/usr/bin/env bash
# ============================================================
# bootstrap-homelab.sh — One-shot K3s cluster bootstrap for SentinelRAG
# ============================================================
# Goes from "fresh Linux nodes with SSH access" to "kubectl-ready 3-node
# K3s cluster with MetalLB + local registry + Temporal + Ollama," then
# hands off to deploy-homelab.sh for the application install.
#
# Targets the standard 3-node homelab layout (override via env vars):
#   k8s-node1  192.168.0.101  control-plane + worker  (NODE1_IP)
#   k8s-node2  192.168.0.102  worker                  (NODE2_IP)
#   k8s-node3  192.168.0.103  worker                  (NODE3_IP)
#   SSH user:  labadmin                               (NODE_USER)
#
# All defaults overridable:
#   NODE_USER, NODE1_IP, NODE2_IP, NODE3_IP, NODE1_NAME, NODE2_NAME,
#   NODE3_NAME, METALLB_RANGE, K3S_VERSION
#
# Credentials (NEVER hardcoded):
#   - First, the script tries SSH key auth (idempotent — re-runs are free).
#   - If key auth fails, it falls back to password auth via sshpass.
#   - Passwords read from env vars HOMELAB_NODE{1,2,3}_PASS, or prompted
#     interactively (read -s) if unset. Never written to disk.
#
# Usage:
#   ./homelabsetup/bootstrap-homelab.sh                 # bootstrap only
#   ./homelabsetup/bootstrap-homelab.sh --deploy        # bootstrap + app deploy
#   ./homelabsetup/bootstrap-homelab.sh --skip-prereqs  # K3s only, no MetalLB
#   ./homelabsetup/bootstrap-homelab.sh --skip-temporal # Skip Temporal install
#   ./homelabsetup/bootstrap-homelab.sh --skip-ollama   # Skip Ollama install
#   ./homelabsetup/bootstrap-homelab.sh --teardown      # uninstall K3s
# ============================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_USER="${NODE_USER:-labadmin}"
NODE1_IP="${NODE1_IP:-192.168.0.101}"
NODE2_IP="${NODE2_IP:-192.168.0.102}"
NODE3_IP="${NODE3_IP:-192.168.0.103}"
NODE1_NAME="${NODE1_NAME:-k8s-node1}"
NODE2_NAME="${NODE2_NAME:-k8s-node2}"
NODE3_NAME="${NODE3_NAME:-k8s-node3}"
NODES_IP=("$NODE1_IP" "$NODE2_IP" "$NODE3_IP")
NODES_NAME=("$NODE1_NAME" "$NODE2_NAME" "$NODE3_NAME")

METALLB_RANGE="${METALLB_RANGE:-192.168.0.200-192.168.0.220}"
METALLB_VERSION="${METALLB_VERSION:-v0.14.8}"

REGISTRY_HOST="registry.local"
REGISTRY_NODEPORT="30500"

# Pin K3s — re-bootstrapping should NOT silently roll the cluster forward.
# Override with K3S_VERSION when you genuinely want to upgrade.
K3S_VERSION="${K3S_VERSION:-v1.34.6+k3s1}"

LOCAL_KUBECONFIG="${LOCAL_KUBECONFIG:-$HOME/.kube/config-sentinelrag-homelab}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"

NAMESPACE_APP="sentinelrag"
NAMESPACE_TEMPORAL="temporal"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

# ── Flags ───────────────────────────────────────────────────
DO_DEPLOY=false
SKIP_PREREQS=false
SKIP_TEMPORAL=false
SKIP_OLLAMA=false
TEARDOWN=false
CONFIGURE_SUDO=false

for arg in "$@"; do
  case $arg in
    --deploy)          DO_DEPLOY=true ;;
    --skip-prereqs)    SKIP_PREREQS=true ;;
    --skip-temporal)   SKIP_TEMPORAL=true ;;
    --skip-ollama)     SKIP_OLLAMA=true ;;
    --teardown)        TEARDOWN=true ;;
    --configure-sudo)  CONFIGURE_SUDO=true ;;
    -h|--help)
      sed -n '2,40p' "$0"; exit 0 ;;
    *) echo -e "${RED}Unknown flag: $arg${NC}"; exit 1 ;;
  esac
done

# ── Helpers ─────────────────────────────────────────────────
log()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
error()  { echo -e "${RED}[x]${NC} $*"; exit 1; }
header() { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || error "$1 is required but not installed."
}

# Index 0/1/2 → password env var → fallback to prompt
get_password() {
  local idx=$1
  local var="HOMELAB_NODE$((idx+1))_PASS"
  local val="${!var:-}"
  if [ -n "$val" ]; then
    echo "$val"
    return
  fi
  read -srp "Password for ${NODE_USER}@${NODES_IP[$idx]}: " val
  echo >&2
  echo "$val"
}

# SSH wrapper that tries key auth first, falls back to sshpass if available.
# Args: node-index, remote-command-string
ssh_node() {
  local idx=$1
  shift
  local ip="${NODES_IP[$idx]}"
  local cmd="$*"

  # Key auth attempt — silent if it works.
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=no \
         -i "$SSH_KEY" "${NODE_USER}@${ip}" \
         "$cmd" 2>/dev/null; then
    return 0
  fi

  # Fallback: password via sshpass.
  if ! command -v sshpass >/dev/null 2>&1; then
    error "Key auth to ${NODE_USER}@${ip} failed and sshpass is not installed. Either: (1) run 'ssh-copy-id ${NODE_USER}@${ip}' to install your key, or (2) install sshpass (apt/brew/choco)."
  fi

  local pass
  pass=$(get_password "$idx")
  sshpass -p "$pass" ssh -o StrictHostKeyChecking=no \
    "${NODE_USER}@${ip}" "$cmd"
}

# Same but copies a file (scp) to a node.
scp_to_node() {
  local idx=$1
  local src=$2
  local dst=$3
  local ip="${NODES_IP[$idx]}"

  if scp -o BatchMode=yes -o StrictHostKeyChecking=no \
        -i "$SSH_KEY" "$src" "${NODE_USER}@${ip}:${dst}" 2>/dev/null; then
    return 0
  fi

  if ! command -v sshpass >/dev/null 2>&1; then
    error "scp via key auth failed. Either install your key or install sshpass."
  fi
  local pass
  pass=$(get_password "$idx")
  sshpass -p "$pass" scp -o StrictHostKeyChecking=no \
    "$src" "${NODE_USER}@${ip}:${dst}"
}

# ── Preflight ───────────────────────────────────────────────
header "Step 0 — Preflight"
require_cmd ssh
require_cmd kubectl
require_cmd helm
require_cmd curl

mkdir -p "$(dirname "$LOCAL_KUBECONFIG")"

# ── Teardown ────────────────────────────────────────────────
if [ "$TEARDOWN" = true ]; then
  header "TEARDOWN — Uninstalling K3s from every node"
  warn "This stops K3s on all 3 nodes and deletes /var/lib/rancher/k3s."
  read -rp "Type 'yes' to confirm: " confirm
  [ "$confirm" = "yes" ] || { echo "Aborted."; exit 0; }
  for idx in 0 1 2; do
    log "Tearing down ${NODES_IP[$idx]}..."
    # k3s-uninstall.sh on server, k3s-agent-uninstall.sh on workers — try both.
    ssh_node "$idx" "sudo /usr/local/bin/k3s-uninstall.sh 2>/dev/null || sudo /usr/local/bin/k3s-agent-uninstall.sh 2>/dev/null || true"
  done
  log "Teardown complete."
  exit 0
fi

# ── Step 1 — Install K3s server on node1 ────────────────────
header "Step 1 — Install K3s server on ${NODE1_NAME} (${NODE1_IP})"

# Idempotent: skip install if k3s is already there at the pinned version.
EXISTING_VER=$(ssh_node 0 "sudo k3s --version 2>/dev/null | head -1 | awk '{print \$3}' || true")
if [ "$EXISTING_VER" = "$K3S_VERSION" ]; then
  log "K3s ${K3S_VERSION} already installed on ${NODE1_NAME}."
else
  if [ -n "$EXISTING_VER" ]; then
    warn "K3s ${EXISTING_VER} already on ${NODE1_NAME}; the pinned version is ${K3S_VERSION}."
    warn "Re-run with --teardown first if you want to switch versions."
  fi
  log "Installing K3s server (this fetches ${K3S_VERSION})..."
  ssh_node 0 "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=${K3S_VERSION} INSTALL_K3S_EXEC='server --node-name=${NODE1_NAME} --write-kubeconfig-mode=644 --disable=servicelb' sh -"
fi

log "Fetching node-token from ${NODE1_NAME}..."
NODE_TOKEN=$(ssh_node 0 "sudo cat /var/lib/rancher/k3s/server/node-token")
[ -n "$NODE_TOKEN" ] || error "Could not read node-token from ${NODE1_NAME}."

# ── Step 2 — Join workers ────────────────────────────────────
header "Step 2 — Join workers to the cluster"

for idx in 1 2; do
  AGENT_VER=$(ssh_node "$idx" "sudo k3s --version 2>/dev/null | head -1 | awk '{print \$3}' || true")
  if [ "$AGENT_VER" = "$K3S_VERSION" ]; then
    log "K3s agent ${K3S_VERSION} already on ${NODES_NAME[$idx]}."
    continue
  fi
  log "Joining ${NODES_NAME[$idx]} (${NODES_IP[$idx]})..."
  ssh_node "$idx" "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=${K3S_VERSION} K3S_URL=https://${NODE1_IP}:6443 K3S_TOKEN='${NODE_TOKEN}' INSTALL_K3S_EXEC='agent --node-name=${NODES_NAME[$idx]}' sh -"
done

# ── Step 3 — Export kubeconfig ──────────────────────────────
header "Step 3 — Export kubeconfig to ${LOCAL_KUBECONFIG}"

# Pull kubeconfig, swap 127.0.0.1 → node1 public IP so it's usable from the
# build host.
RAW_KUBECONFIG=$(ssh_node 0 "sudo cat /etc/rancher/k3s/k3s.yaml")
echo "$RAW_KUBECONFIG" | sed "s/127.0.0.1/${NODE1_IP}/g" > "$LOCAL_KUBECONFIG"
chmod 600 "$LOCAL_KUBECONFIG"
log "Kubeconfig written. Export it for subsequent kubectl commands:"
log "  export KUBECONFIG=$LOCAL_KUBECONFIG"
export KUBECONFIG="$LOCAL_KUBECONFIG"

# Quick reachability check.
kubectl get nodes >/dev/null 2>&1 || error "kubectl cannot reach ${NODE1_IP}:6443 — check firewall."
log "Cluster reachable. Nodes:"
kubectl get nodes -o wide

# ── Step 4 — /etc/hosts + registries.yaml on every node ────
header "Step 4 — Configure /etc/hosts + registries.yaml on every node"

# Both pieces are idempotent — re-running is free.
for idx in 0 1 2; do
  log "Configuring ${NODES_NAME[$idx]} (${NODES_IP[$idx]})..."
  ssh_node "$idx" "bash -s" <<REMOTE
set -euo pipefail
# /etc/hosts → registry.local
if ! grep -q "registry.local" /etc/hosts; then
  echo "${NODE1_IP} ${REGISTRY_HOST}" | sudo tee -a /etc/hosts >/dev/null
fi
# K3s containerd mirror config — this is THE critical file. Without it,
# every locally-built image ImagePullBackOffs because containerd treats
# registry.local:30500 as unknown and falls back to HTTPS.
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<YAML
mirrors:
  "${REGISTRY_HOST}:${REGISTRY_NODEPORT}":
    endpoint:
      - "http://${NODE1_IP}:${REGISTRY_NODEPORT}"
  "${NODE1_IP}:${REGISTRY_NODEPORT}":
    endpoint:
      - "http://${NODE1_IP}:${REGISTRY_NODEPORT}"
YAML
# Restart K3s so containerd re-reads the mirror config.
if systemctl is-active --quiet k3s; then
  sudo systemctl restart k3s
elif systemctl is-active --quiet k3s-agent; then
  sudo systemctl restart k3s-agent
fi
REMOTE
done

log "Waiting for cluster to settle after K3s restart..."
sleep 10
kubectl wait --for=condition=Ready node --all --timeout=120s

# ── Step 5 — Prereqs: MetalLB ───────────────────────────────
if [ "$SKIP_PREREQS" = false ]; then
  header "Step 5 — MetalLB ${METALLB_VERSION}"

  if kubectl get namespace metallb-system >/dev/null 2>&1; then
    log "MetalLB already installed."
  else
    kubectl apply -f "https://raw.githubusercontent.com/metallb/metallb/${METALLB_VERSION}/config/manifests/metallb-native.yaml"
    log "Waiting for MetalLB controller..."
    kubectl -n metallb-system wait --for=condition=available --timeout=180s deployment/controller
  fi

  log "Applying IPAddressPool + L2Advertisement for ${METALLB_RANGE}..."
  cat <<YAML | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: sentinelrag-pool
  namespace: metallb-system
spec:
  addresses:
    - ${METALLB_RANGE}
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: sentinelrag-l2
  namespace: metallb-system
spec:
  ipAddressPools:
    - sentinelrag-pool
YAML
  log "MetalLB configured."
fi

# ── Step 6 — Local container registry ───────────────────────
header "Step 6 — Local container registry (registry.local:${REGISTRY_NODEPORT})"

if kubectl -n registry get deployment registry >/dev/null 2>&1; then
  log "Registry already deployed."
else
  ssh_node 0 "sudo mkdir -p /opt/registry"
  # Unquoted heredoc → bash expands $NODE1_NAME / $REGISTRY_NODEPORT here.
  cat <<YAML | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: registry
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: registry-pv
spec:
  capacity:
    storage: 30Gi
  accessModes: [ReadWriteOnce]
  hostPath:
    path: /opt/registry
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values: ["${NODE1_NAME}"]
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: registry-data
  namespace: registry
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ""
  volumeName: registry-pv
  resources:
    requests:
      storage: 30Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: registry
  namespace: registry
spec:
  replicas: 1
  selector:
    matchLabels:
      app: registry
  template:
    metadata:
      labels:
        app: registry
    spec:
      nodeSelector:
        kubernetes.io/hostname: ${NODE1_NAME}
      containers:
        - name: registry
          image: registry:2
          ports:
            - containerPort: 5000
          volumeMounts:
            - name: data
              mountPath: /var/lib/registry
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: registry-data
---
apiVersion: v1
kind: Service
metadata:
  name: registry
  namespace: registry
spec:
  type: NodePort
  selector:
    app: registry
  ports:
    - port: 5000
      targetPort: 5000
      nodePort: ${REGISTRY_NODEPORT}
YAML

  log "Waiting for registry pod..."
  kubectl -n registry wait --for=condition=ready pod -l app=registry --timeout=60s
fi

# Verify from the build host.
if curl -sf --max-time 5 "http://${REGISTRY_HOST}:${REGISTRY_NODEPORT}/v2/_catalog" >/dev/null 2>&1; then
  log "Registry reachable at http://${REGISTRY_HOST}:${REGISTRY_NODEPORT}"
elif curl -sf --max-time 5 "http://${NODE1_IP}:${REGISTRY_NODEPORT}/v2/_catalog" >/dev/null 2>&1; then
  warn "Registry reachable by IP only — add to your hosts file:"
  warn "  ${NODE1_IP} ${REGISTRY_HOST}"
  warn "Docker Desktop also needs ${REGISTRY_HOST}:${REGISTRY_NODEPORT} in insecure-registries."
else
  warn "Registry pod up but not reachable from the build host. Likely firewall on port ${REGISTRY_NODEPORT}."
fi

# ── Step 7 — Temporal cluster ────────────────────────────────
if [ "$SKIP_TEMPORAL" = false ]; then
  header "Step 7 — Temporal cluster (namespace=${NAMESPACE_TEMPORAL})"

  if kubectl get namespace "$NAMESPACE_TEMPORAL" >/dev/null 2>&1 \
       && helm -n "$NAMESPACE_TEMPORAL" status temporal >/dev/null 2>&1; then
    log "Temporal already installed."
  else
    kubectl create namespace "$NAMESPACE_TEMPORAL" 2>/dev/null || true

    # Required secret for the persistence store (per the bundled values).
    if ! kubectl -n "$NAMESPACE_TEMPORAL" get secret temporal-default-store >/dev/null 2>&1; then
      kubectl -n "$NAMESPACE_TEMPORAL" create secret generic temporal-default-store \
        --from-literal=password="$(openssl rand -base64 16 | tr -d '=/+' | head -c 24)"
    fi
    if ! kubectl -n "$NAMESPACE_TEMPORAL" get secret temporal-visibility-store >/dev/null 2>&1; then
      kubectl -n "$NAMESPACE_TEMPORAL" create secret generic temporal-visibility-store \
        --from-literal=password="$(openssl rand -base64 16 | tr -d '=/+' | head -c 24)"
    fi

    helm repo add temporal https://go.temporal.io/helm-charts >/dev/null 2>&1 || true
    helm repo update temporal >/dev/null

    log "Installing Temporal (this brings up its own Postgres sub-chart)..."
    helm upgrade --install temporal temporal/temporal \
      -n "$NAMESPACE_TEMPORAL" \
      -f "$REPO_ROOT/infra/bootstrap/temporal/values.yaml" \
      --timeout 10m
  fi
fi

# ── Step 8 — Ollama ──────────────────────────────────────────
if [ "$SKIP_OLLAMA" = false ]; then
  header "Step 8 — Ollama (namespace=${NAMESPACE_APP})"

  kubectl create namespace "$NAMESPACE_APP" 2>/dev/null || true

  cat <<'YAML' | kubectl apply -n "$NAMESPACE_APP" -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-models
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources:
    requests:
      storage: 30Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  labels:
    app: ollama
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  strategy:
    type: Recreate  # Only one pod can mount the PVC.
  template:
    metadata:
      labels:
        app: ollama
    spec:
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - containerPort: 11434
          env:
            - name: OLLAMA_KEEP_ALIVE
              value: 24h
          resources:
            requests:
              cpu: 250m
              memory: 1Gi
            limits:
              cpu: "4"
              memory: 8Gi
          volumeMounts:
            - name: models
              mountPath: /root/.ollama
      volumes:
        - name: models
          persistentVolumeClaim:
            claimName: ollama-models
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
spec:
  selector:
    app: ollama
  ports:
    - name: http
      port: 11434
      targetPort: 11434
YAML

  log "Waiting for Ollama pod..."
  kubectl -n "$NAMESPACE_APP" rollout status deployment/ollama --timeout=180s
fi

# ── Step 9 — Optional deploy chain ──────────────────────────
if [ "$DO_DEPLOY" = true ]; then
  header "Step 9 — Handoff to deploy-homelab.sh"
  exec "$REPO_ROOT/homelabsetup/deploy-homelab.sh" --skip-registry
fi

header "Bootstrap complete"
echo "Next steps:"
echo "  export KUBECONFIG=$LOCAL_KUBECONFIG"
echo "  $REPO_ROOT/homelabsetup/deploy-homelab.sh"
