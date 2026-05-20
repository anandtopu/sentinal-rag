#!/usr/bin/env bash
# ============================================================
# fresh-deploy-homelab.sh — Clean slate redeploy
# ============================================================
# Sequence:
#   1. cleanup-homelab.sh --all      (wipe app + data, KEEP cluster)
#   2. bootstrap-homelab.sh --skip-prereqs (re-ensure registry + temporal + ollama)
#   3. deploy-homelab.sh             (build + push + helm install)
#
# Use when:
#   - You changed the Helm chart schema and `helm upgrade` is unhappy
#   - You want to verify the deploy from a clean state
#   - You're chasing a "this only repro's on fresh install" bug
#
# Use bootstrap-homelab.sh --teardown FIRST if you want to also reinstall
# K3s itself. This script does NOT do that.
#
# Flags:
#   --yes / -y    Skip the destructive-action confirmation prompts.
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()    { echo -e "${GREEN}[+]${NC} $*"; }
header() { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }
error()  { echo -e "${RED}[x]${NC} $*"; exit 1; }

NO_CONFIRM=()
for arg in "$@"; do
  case $arg in
    --yes|-y) NO_CONFIRM=(--yes) ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) error "Unknown flag: $arg" ;;
  esac
done

header "Step 1 — Cleanup (--all)"
"$REPO_ROOT/homelabsetup/cleanup-homelab.sh" --all "${NO_CONFIRM[@]}"

header "Step 2 — Bootstrap (registry + Temporal + Ollama)"
# --skip-prereqs assumes K3s + MetalLB are already there; the cleanup
# script doesn't touch the cluster itself. Re-running the registry +
# Temporal + Ollama install paths is idempotent.
"$REPO_ROOT/homelabsetup/bootstrap-homelab.sh" --skip-prereqs

header "Step 3 — Deploy"
"$REPO_ROOT/homelabsetup/deploy-homelab.sh"

log "Fresh deploy complete."
