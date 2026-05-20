#!/usr/bin/env bash
# ============================================================
# restart-homelab.sh — Rollout-restart every SentinelRAG workload
# ============================================================
# Triggers a fresh pod rollout without re-pulling images. Useful for:
#   - Picking up a Secret / ConfigMap change
#   - Recovering a hung pod
#   - Forcing Temporal worker reconnection
#
# Does NOT rebuild or push images — use deploy-homelab.sh for that.
# Does NOT touch the in-cluster dependencies (Postgres / Redis / MinIO /
# Keycloak / Unleash / Temporal / Ollama) — those keep running.
# ============================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-sentinelrag}"
RELEASE="${RELEASE:-sentinelrag}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
header() { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }

DEPLOYMENTS=(
  "${RELEASE}-api"
  "${RELEASE}-retrieval"
  "${RELEASE}-temporal-worker"
  "${RELEASE}-frontend"
)

header "Restarting SentinelRAG application deployments"

for dep in "${DEPLOYMENTS[@]}"; do
  if kubectl -n "$NAMESPACE" get deployment "$dep" >/dev/null 2>&1; then
    log "rollout restart ${dep}"
    kubectl -n "$NAMESPACE" rollout restart deployment/"$dep" >/dev/null
  else
    warn "Deployment $dep not found — skipping."
  fi
done

header "Waiting for rollouts"

for dep in "${DEPLOYMENTS[@]}"; do
  if kubectl -n "$NAMESPACE" get deployment "$dep" >/dev/null 2>&1; then
    kubectl -n "$NAMESPACE" rollout status deployment/"$dep" --timeout=300s \
      || warn "$dep did not become ready in time."
  fi
done

header "Pod status"
kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/part-of=sentinelrag -o wide
