#!/usr/bin/env bash
# Daily backup-health check for the SentinelRAG AWS environment.
#
# Asserts:
#   - RDS automated snapshot for sentinelrag-<env>-db is < 26 h old.
#   - S3 documents bucket has Versioning = Enabled.
#   - S3 audit bucket has Object Lock = COMPLIANCE with retention years > 0.
#
# Emits a JSON status doc on stdout and exits non-zero on any failure so
# the CI workflow surfaces the alert.

set -euo pipefail

ENV="${SENTINELRAG_ENV:-dev}"
PREFIX="${SENTINELRAG_PREFIX:-sentinelrag-${ENV}}"
DB_ID="${SENTINELRAG_DB_ID:-${PREFIX}-db}"
DOCS_BUCKET="${SENTINELRAG_DOCS_BUCKET:-${PREFIX}-documents}"
AUDIT_BUCKET="${SENTINELRAG_AUDIT_BUCKET:-${PREFIX}-audit}"
MAX_SNAPSHOT_AGE_HOURS="${SENTINELRAG_MAX_SNAPSHOT_AGE_HOURS:-26}"

# We collect failures into an array and report them all at the end so a
# single misconfigured check doesn't mask the others.
declare -a failures=()
declare -A results=()

# Helper: record a check's outcome.
record() {
  local name="$1" status="$2" detail="$3"
  results[$name]="$status:$detail"
  if [[ "$status" != "ok" ]]; then
    failures+=("$name: $detail")
  fi
}

echo "Verifying AWS backups for env=${ENV} prefix=${PREFIX}" >&2

# --- 1. RDS snapshot freshness ---
latest_snapshot_time=$(
  aws rds describe-db-snapshots \
    --db-instance-identifier "$DB_ID" \
    --snapshot-type automated \
    --query 'reverse(sort_by(DBSnapshots,&SnapshotCreateTime))[0].SnapshotCreateTime' \
    --output text 2>/dev/null || echo "NONE"
)

if [[ "$latest_snapshot_time" == "NONE" || -z "$latest_snapshot_time" || "$latest_snapshot_time" == "None" ]]; then
  record "rds_snapshot" "missing" "no automated snapshot found for $DB_ID"
else
  # `date -d` is GNU; matches GitHub Actions ubuntu-latest. macOS users can
  # install gdate or run from CI.
  snapshot_epoch=$(date -d "$latest_snapshot_time" +%s)
  now_epoch=$(date +%s)
  age_hours=$(( (now_epoch - snapshot_epoch) / 3600 ))
  if (( age_hours > MAX_SNAPSHOT_AGE_HOURS )); then
    record "rds_snapshot" "stale" "latest snapshot is ${age_hours}h old (> ${MAX_SNAPSHOT_AGE_HOURS}h)"
  else
    record "rds_snapshot" "ok" "latest snapshot ${age_hours}h old"
  fi
fi

# --- 2. Documents bucket versioning ---
docs_versioning=$(
  aws s3api get-bucket-versioning \
    --bucket "$DOCS_BUCKET" \
    --query 'Status' \
    --output text 2>/dev/null || echo "MISSING"
)

if [[ "$docs_versioning" == "Enabled" ]]; then
  record "docs_versioning" "ok" "Enabled"
else
  record "docs_versioning" "broken" "documents bucket versioning is ${docs_versioning}"
fi

# --- 3. Audit bucket Object Lock ---
audit_lock=$(
  aws s3api get-object-lock-configuration \
    --bucket "$AUDIT_BUCKET" \
    --output json 2>/dev/null || echo '{"ObjectLockConfiguration":{}}'
)

audit_mode=$(echo "$audit_lock" | jq -r '.ObjectLockConfiguration.Rule.DefaultRetention.Mode // "MISSING"')
audit_years=$(echo "$audit_lock" | jq -r '.ObjectLockConfiguration.Rule.DefaultRetention.Years // 0')

if [[ "$audit_mode" != "COMPLIANCE" ]]; then
  record "audit_lock_mode" "broken" "audit bucket Object Lock mode is ${audit_mode}"
else
  record "audit_lock_mode" "ok" "$audit_mode"
fi

if (( audit_years < 1 )); then
  record "audit_retention" "broken" "audit retention years = ${audit_years}"
else
  record "audit_retention" "ok" "${audit_years} years"
fi

# --- Output ---
{
  echo '{'
  echo '  "env":' "\"$ENV\","
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

echo "All AWS backup checks passed." >&2
