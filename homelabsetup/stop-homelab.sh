#!/usr/bin/env bash
# ============================================================
# stop-homelab.sh — Scale every SentinelRAG workload to zero
# ============================================================
# Saves resources without losing state. PVCs stay; pods go.
# Includes the in-cluster dependencies (Postgres / Redis / MinIO /
# Keycloak / Unleash / Ollama / Temporal) so the whole footprint drops
# to ~0 CPU after this.
#
# Bring it all back with `start-homelab.sh` (or re-run deploy-homelab.sh).
#
# Flags:
#   --app-only      Only scale down the app deployments; leave deps running.
# ============================================================

set -euo pipefail

NAMESPACE_APP="${NAMESPACE_APP:-sentinelrag}"
NAMESPACE_TEMPORAL="${NAMESPACE_TEMPORAL:-temporal}"
RELEASE="${RELEASE:-sentinelrag}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
header() { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }

APP_ONLY=false
for arg in "$@"; do
  case $arg in
    --app-only) APP_ONLY=true ;;
    -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

scale_zero() {
  local ns=$1
  local kind=$2  # deployment or statefulset
  local label=$3
  local count
  count=$(kubectl -n "$ns" get "$kind" -l "$label" -o name 2>/dev/null | wc -l)
  if [ "$count" -eq 0 ]; then
    return 0
  fi
  log "Scaling ${count} ${kind}(s) in ${ns} matching ${label} to 0..."
  kubectl -n "$ns" scale "$kind" -l "$label" --replicas=0 >/dev/null
}

header "Scaling SentinelRAG app deployments to 0"
scale_zero "$NAMESPACE_APP" deployment "app.kubernetes.io/part-of=sentinelrag"
# Ollama is not part of the Helm release — it's a standalone deployment.
scale_zero "$NAMESPACE_APP" deployment "app=ollama"

if [ "$APP_ONLY" = false ]; then
  header "Scaling in-cluster dependencies to 0"
  # Bitnami subcharts use Deployment for redis-master, minio, keycloak,
  # and StatefulSet for postgresql. Use the standard labels they set.
  scale_zero "$NAMESPACE_APP" statefulset "app.kubernetes.io/name=postgresql"
  scale_zero "$NAMESPACE_APP" statefulset "app.kubernetes.io/name=redis"
  scale_zero "$NAMESPACE_APP" deployment  "app.kubernetes.io/name=minio"
  scale_zero "$NAMESPACE_APP" statefulset "app.kubernetes.io/name=keycloak"
  scale_zero "$NAMESPACE_APP" deployment  "app.kubernetes.io/name=unleash"

  header "Scaling Temporal cluster to 0"
  scale_zero "$NAMESPACE_TEMPORAL" deployment "app.kubernetes.io/instance=temporal"
  scale_zero "$NAMESPACE_TEMPORAL" statefulset "app.kubernetes.io/instance=temporal"
else
  warn "--app-only: leaving in-cluster deps + Temporal running."
fi

header "Final state"
kubectl -n "$NAMESPACE_APP" get pods 2>/dev/null || true
if [ "$APP_ONLY" = false ]; then
  kubectl -n "$NAMESPACE_TEMPORAL" get pods 2>/dev/null || true
fi

log "Stopped. Bring back up by re-running ./homelabsetup/deploy-homelab.sh"
