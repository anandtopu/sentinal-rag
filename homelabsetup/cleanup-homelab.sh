#!/usr/bin/env bash
# ============================================================
# cleanup-homelab.sh — Remove SentinelRAG from the K3s homelab
# ============================================================
# Three levels of cleanup:
#   (default)      Helm uninstall, keep PVCs (data preserved)
#   --all          Helm uninstall + delete namespace (DESTRUCTIVE — wipes data)
#   --everything   Above + kill Temporal + Ollama + registry on the cluster.
#                  Use this when you're about to bootstrap a fresh cluster.
#
# Always asks for explicit confirmation on destructive paths.
# ============================================================

set -euo pipefail

NAMESPACE="sentinelrag"
RELEASE="sentinelrag"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

log()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
error()  { echo -e "${RED}[x]${NC} $*"; exit 1; }
header() { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }

LEVEL=app
NO_CONFIRM=false
for arg in "$@"; do
  case $arg in
    --all)        LEVEL=all ;;
    --everything) LEVEL=everything ;;
    -y|--yes)     NO_CONFIRM=true ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) error "Unknown flag: $arg" ;;
  esac
done

confirm() {
  [ "$NO_CONFIRM" = true ] && return 0
  read -rp "Type 'yes' to confirm: " ans
  [ "$ans" = "yes" ] || { echo "Aborted."; exit 0; }
}

command -v kubectl >/dev/null 2>&1 || error "kubectl not found."
command -v helm    >/dev/null 2>&1 || error "helm not found."

header "Cleanup level: ${LEVEL}"

case $LEVEL in
  app)
    log "Helm-uninstalling ${RELEASE} from ${NAMESPACE} (PVCs preserved)..."
    helm -n "$NAMESPACE" uninstall "$RELEASE" --ignore-not-found
    ;;
  all)
    warn "This deletes the ${NAMESPACE} namespace + ALL PVCs (Postgres, MinIO, Keycloak, Ollama)."
    confirm
    helm -n "$NAMESPACE" uninstall "$RELEASE" --ignore-not-found 2>/dev/null || true
    kubectl delete namespace "$NAMESPACE" --ignore-not-found
    ;;
  everything)
    warn "This deletes the ${NAMESPACE} namespace, the temporal namespace,"
    warn "the registry namespace, and ALL persistent data on every node."
    confirm
    helm -n "$NAMESPACE" uninstall "$RELEASE" --ignore-not-found 2>/dev/null || true
    kubectl delete namespace "$NAMESPACE"  --ignore-not-found
    helm -n temporal uninstall temporal --ignore-not-found 2>/dev/null || true
    kubectl delete namespace temporal      --ignore-not-found
    kubectl delete namespace registry      --ignore-not-found
    # Orphaned PV (registry uses a hostPath PV that survives namespace delete).
    kubectl delete pv registry-pv          --ignore-not-found
    ;;
esac

log "Remaining pods in ${NAMESPACE}:"
kubectl get pods -n "$NAMESPACE" 2>/dev/null || echo "  (namespace gone)"

log "Cleanup complete."
