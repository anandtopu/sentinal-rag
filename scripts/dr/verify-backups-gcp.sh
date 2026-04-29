#!/usr/bin/env bash
# Daily backup-health check for the SentinelRAG GCP environment.
#
# Asserts:
#   - Cloud SQL has at least one automated backup < 26 h old.
#   - GCS documents bucket has versioning enabled.
#   - GCS audit bucket has a locked retention policy with retention > 0.

set -euo pipefail

PROJECT="${SENTINELRAG_GCP_PROJECT:?SENTINELRAG_GCP_PROJECT must be set}"
ENV="${SENTINELRAG_ENV:-dev}"
PREFIX="${SENTINELRAG_PREFIX:-sentinelrag-${ENV}}"
DB_INSTANCE="${SENTINELRAG_DB_ID:-${PREFIX}-db}"
DOCS_BUCKET="${SENTINELRAG_DOCS_BUCKET:-${PREFIX}-documents}"
AUDIT_BUCKET="${SENTINELRAG_AUDIT_BUCKET:-${PREFIX}-audit}"
MAX_BACKUP_AGE_HOURS="${SENTINELRAG_MAX_SNAPSHOT_AGE_HOURS:-26}"

declare -a failures=()
declare -A results=()

record() {
  local name="$1" status="$2" detail="$3"
  results[$name]="$status:$detail"
  if [[ "$status" != "ok" ]]; then
    failures+=("$name: $detail")
  fi
}

echo "Verifying GCP backups for project=${PROJECT} env=${ENV} prefix=${PREFIX}" >&2

# --- 1. Cloud SQL backup freshness ---
latest_backup=$(
  gcloud sql backups list \
    --instance="$DB_INSTANCE" \
    --project="$PROJECT" \
    --filter='status=SUCCESSFUL' \
    --sort-by='~startTime' \
    --limit=1 \
    --format='value(startTime)' 2>/dev/null || echo "NONE"
)

if [[ "$latest_backup" == "NONE" || -z "$latest_backup" ]]; then
  record "cloudsql_backup" "missing" "no successful backup found for $DB_INSTANCE"
else
  backup_epoch=$(date -d "$latest_backup" +%s)
  now_epoch=$(date +%s)
  age_hours=$(( (now_epoch - backup_epoch) / 3600 ))
  if (( age_hours > MAX_BACKUP_AGE_HOURS )); then
    record "cloudsql_backup" "stale" "latest backup is ${age_hours}h old (> ${MAX_BACKUP_AGE_HOURS}h)"
  else
    record "cloudsql_backup" "ok" "latest backup ${age_hours}h old"
  fi
fi

# --- 2. Documents bucket versioning ---
docs_versioning=$(
  gcloud storage buckets describe "gs://${DOCS_BUCKET}" \
    --project="$PROJECT" \
    --format='value(versioning.enabled)' 2>/dev/null || echo "MISSING"
)

if [[ "$docs_versioning" == "True" ]]; then
  record "docs_versioning" "ok" "Enabled"
else
  record "docs_versioning" "broken" "documents bucket versioning is ${docs_versioning}"
fi

# --- 3. Audit bucket retention policy ---
audit_policy=$(
  gcloud storage buckets describe "gs://${AUDIT_BUCKET}" \
    --project="$PROJECT" \
    --format=json 2>/dev/null || echo '{}'
)

audit_locked=$(echo "$audit_policy" | jq -r '.retention_policy.is_locked // false')
audit_retention_seconds=$(echo "$audit_policy" | jq -r '.retention_policy.retention_period // 0')

if [[ "$audit_locked" != "true" ]]; then
  record "audit_lock" "broken" "audit retention is_locked=${audit_locked}"
else
  record "audit_lock" "ok" "is_locked=true"
fi

if (( audit_retention_seconds < 1 )); then
  record "audit_retention" "broken" "audit retention seconds = ${audit_retention_seconds}"
else
  retention_years=$(awk -v s="$audit_retention_seconds" 'BEGIN{printf "%.1f", s/31557600}')
  record "audit_retention" "ok" "${retention_years} years (${audit_retention_seconds}s)"
fi

# --- Output ---
{
  echo '{'
  echo '  "env":' "\"$ENV\","
  echo '  "project":' "\"$PROJECT\","
  echo '  "checks": {'
  first=1
  for k in "${!results[@]}"; do
    [[ $first -eq 0 ]] && echo ','
    first=0
    status="${results[$k]%%:*}"
    detail="${results[$k]#*:}"
    echo -n "    \"$k\": {\"status\":\"$status\",\"detail\":\"$detail\"}"
  done
  echo
  echo '  },'
  echo '  "ok":' $([[ ${#failures[@]} -eq 0 ]] && echo true || echo false)
  echo '}'
}

if (( ${#failures[@]} > 0 )); then
  echo "BACKUP VERIFICATION FAILED:" >&2
  for f in "${failures[@]}"; do
    echo "  - $f" >&2
  done
  exit 1
fi

echo "All GCP backup checks passed." >&2
