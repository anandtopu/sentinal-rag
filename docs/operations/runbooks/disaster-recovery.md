# Disaster recovery runbook

How SentinelRAG recovers from infrastructure-level failures. Read this end-to-end **before** an incident — the worst time to learn the recovery flow is at 3 AM during one.

## RPO / RTO targets

| Tier | Component | RPO (data loss tolerated) | RTO (time to recover) |
|---|---|---|---|
| Tier 0 | Audit log | **0** (immutable, dual-written) | n/a — audit is written-or-rejected, not "recovered" |
| Tier 1 | Postgres (tenants, RBAC, query sessions, audit mirror) | 5 min | 1 h |
| Tier 1 | S3 / GCS documents bucket | 24 h (versioned; recover prior version) | 2 h |
| Tier 2 | Redis cache | n/a — cold-start tolerated | 15 min |
| Tier 2 | Temporal cluster (workflow state) | 5 min (Postgres-backed) | 1 h |
| Tier 3 | Eval results, metrics, traces | 1 h | best-effort |

**Tier 0 is non-negotiable.** ADR-0016 / ADR-0026 commit us to immutable audit via Object Lock COMPLIANCE (S3) / Locked Retention Policy (GCS). Audit recovery is "the bytes are still there" — there is no restore procedure because there is no loss procedure.

**Tier 1 + 2 RPO/RTO are achievable on the dev environment with the Phase 7/8 Terraform + Helm shape.** Numbers tighten in prod once we ramp HA — see ADR-0028 for the path.

## Failure scenarios

Each scenario lists symptoms, the immediate response, the recovery procedure, and the post-incident actions.

---

### S1. RDS Postgres failure (single-AZ outage / instance corrupt)

**Symptoms**
- API `/health` returns 503 with `db.unavailable`.
- `sentinelrag_queries_total{status="error"}` rate spike in Grafana.
- RDS console shows the instance in `failed` or `inaccessible-encryption-credentials-recoverable` state.

**Immediate response (first 5 min)**
1. Confirm scope: `aws rds describe-db-instances --db-instance-identifier sentinelrag-dev-db --query 'DBInstances[0].DBInstanceStatus'`.
2. Check the AWS Service Health Dashboard for a regional issue. If regional, jump to **S6 (region outage)**.
3. Page the on-call (Slack `#sentinelrag-oncall` for the portfolio demo; in prod replace with real PagerDuty).

**Recovery procedure**
1. **Multi-AZ failover (if Multi-AZ enabled — prod default):** AWS handles it automatically. RTO ≈ 60–120 s. Confirm by re-running `aws rds describe-db-instances`.
2. **Restore from latest automated snapshot (single-AZ — dev default):**
   ```bash
   # Find the latest automated snapshot.
   aws rds describe-db-snapshots \
     --db-instance-identifier sentinelrag-dev-db \
     --snapshot-type automated \
     --query 'reverse(sort_by(DBSnapshots,&SnapshotCreateTime))[0].DBSnapshotIdentifier' \
     --output text

   # Restore into a new instance (cannot restore-in-place).
   aws rds restore-db-instance-from-db-snapshot \
     --db-instance-identifier sentinelrag-dev-db-restored \
     --db-snapshot-identifier <id-from-above> \
     --db-subnet-group-name sentinelrag-dev-rds \
     --vpc-security-group-ids <sg-from-tf-output>
   ```
3. **Cut over the API to the restored endpoint:**
   - In Secrets Manager, edit `sentinelrag-dev/api` → set `DATABASE_URL` host to the restored instance's endpoint.
   - External Secrets Operator picks up the change within `refreshInterval` (1 h default).
   - **To force immediate rollover:** `kubectl -n sentinelrag annotate externalsecret sentinelrag-api-secrets force-sync=$(date +%s) --overwrite`.
4. **Re-run alembic migrations** against the restored instance: `kubectl -n sentinelrag delete job sentinelrag-dev-migrations && helm upgrade --reuse-values sentinelrag-dev infra/helm/sentinelrag` (this re-fires the pre-upgrade migration Job).
5. **Verify**: `POST /api/v1/query` returns 2xx; `sentinelrag_queries_total{status="success"}` recovers in Grafana.

**Data loss expected**
- Up to 5 minutes (RDS automated snapshot frequency × max replication lag at failure time). Anything written between the last snapshot/log shipment and the failure may be lost. Audit events in this window are **still durable on S3** (dual-write) and reconcile back into Postgres on next `AuditReconciliationWorkflow` run.

**Post-incident**
- File issue with timeline + decision points.
- Rotate the master password (`aws secretsmanager update-secret`).
- If snapshot restore was used, schedule the original instance for forensic copy and then deletion.
- Update PHASE_PLAN.md "DR drill log" with the actual RTO measured.

---

### S2. S3/GCS documents bucket — accidental deletion or corruption

**Symptoms**
- Document download endpoints return 404.
- Ingestion workflow activities fail with `NoSuchKey`.

**Immediate response**
1. Confirm bucket exists: `aws s3api head-bucket --bucket sentinelrag-dev-documents`.
2. If the bucket is gone: this is a tier-0 escalation (someone with admin perms ran `aws s3 rb --force`). Audit who and when via CloudTrail before recovering.

**Recovery — versioned object restored**
1. Versioning is on for the documents bucket (Terraform default).
2. List versions for the affected key:
   ```bash
   aws s3api list-object-versions \
     --bucket sentinelrag-dev-documents \
     --prefix tenants/<tenant-id>/<document-id>/
   ```
3. Restore by deleting the delete-marker (the most recent version is then the surviving one):
   ```bash
   aws s3api delete-object \
     --bucket sentinelrag-dev-documents \
     --key <key> --version-id <delete-marker-version-id>
   ```

**Recovery — bucket gone**
1. Re-create from Terraform: `terraform apply -target=module.s3.aws_s3_bucket.documents`.
2. Re-ingest from canonical source (the upstream document store the user originally uploaded from). The bucket has no recovery from "deleted bucket" — versioning protects per-object, not per-bucket.

**Data loss expected**
- For per-key delete: zero (versioning).
- For full bucket loss: total. We do not currently mirror documents cross-region (Phase 9 work).

---

### S3. Audit bucket — Object Lock prevents tampering, but...

**Symptoms / scenario**
- Operator complains: "I need to delete an audit object." They cannot. By design.
- Or: the bucket itself was deleted by an admin.

**Recovery**
- **Object-level deletion is impossible** during the 7-year retention. Object Lock COMPLIANCE mode cannot be overridden by root. This is the guarantee, not a bug.
- **Bucket-level deletion** is also blocked by the bucket policy (`DenyVersionedDelete` / `DenyBucketDelete` statements in the s3 module's `aws_s3_bucket_policy.audit`) — but this is policy, not Object Lock, so a sufficiently-privileged actor can edit the policy and delete. Mitigation: SCP at the org level locking down `s3:DeleteBucket` and `s3:PutBucketPolicy` on tagged audit buckets. Out of scope for the dev environment; document for prod ramp-up.
- If somehow the bucket IS gone, the audit log is **still durable in Postgres** (`audit_events` table) — the dual-write path means the bucket loss reduces audit immutability but does not lose the events. Re-emit them to a fresh bucket via the `AuditReconciliationWorkflow` once the new bucket exists.

---

### S4. Redis (ElastiCache / Memorystore) total failure

**Symptoms**
- API logs show `redis.connection_error` warnings.
- p99 latency rises 10–20 % (cold prompt fetches, JWKS re-fetch on every request).
- No 5xx — the API gracefully degrades (validated by Chaos experiment 03).

**Recovery**
- Redis is a **soft dependency**. Replace the cluster, do not "restore" it.
- `terraform apply -target=module.redis` (AWS) or `module.redis` (GCP) re-creates the cluster.
- No data migration needed — cache is rebuilt on first request.
- Update Secrets Manager `REDIS_URL` if the endpoint changed; ESO refreshes the secret; pods restart on rolling-update.

**Data loss expected**
- All cached entries. None of them are sources of truth — discard freely.

---

### S5. Temporal cluster failure

**Symptoms**
- API endpoints that schedule workflows return 503 with `temporal.unavailable` (document upload, eval run).
- `/query` is **unaffected** (in-process orchestrator; validated by Chaos experiment 04).
- Temporal Web UI 503 / unreachable.

**Recovery**
- Temporal state lives in its own Postgres database (separate from the SentinelRAG `sentinelrag` DB; Temporal's history + visibility stores).
- If the Temporal **frontend pods** are dead but the DB is healthy: `kubectl -n temporal rollout restart deployment temporal-frontend`.
- If the Temporal **DB** is corrupt: restore from snapshot (same procedure as S1, against the Temporal RDS instance).
- After Temporal recovers, **in-flight workflows resume** from their last persisted history event — Temporal's at-least-once semantics handle the activity replay automatically. **Idempotent activity design** (every ingestion + eval activity in `apps/temporal-worker/sentinelrag_worker/activities/`) is what makes this safe.

**Data loss expected**
- Workflow runs in flight at the moment of failure replay from history; their activities re-execute. Designed-for. Audit events emitted by replayed activities are deduped on `(activity_id, event_uuid)`.

---

### S6. Region-wide AWS outage → failover to GCP mirror

**Symptoms**
- Multiple AWS services unreachable in the SentinelRAG region (us-east-1).
- AWS Service Health Dashboard confirms the regional impact.

**Decision: failover or wait?**
- Most regional outages are < 4 h. RTO 1 h means a 3 h regional outage is "ride it out" if you've been awake < 1 h.
- Failover to the GCP mirror only when:
  - AWS health dashboard reports > 4 h ETA, OR
  - Customer-impacting downtime exceeds the SLO budget (track in Grafana SLO panels).

**Failover procedure (active-passive — Phase 8 stance)**
1. Verify the GCP mirror is healthy: `kubectl --context gcp-dev get pods -n sentinelrag` shows everything Running.
2. Update DNS (Route 53 → external GCP IPs):
   ```bash
   # api.sentinelrag.example.com  CNAME → gce-managed-cert hostname
   # app.sentinelrag.example.com  CNAME → gce-managed-cert hostname
   aws route53 change-resource-record-sets --hosted-zone-id <id> \
     --change-batch file://failover-to-gcp.json
   ```
3. The GCP env runs against its own RDS-equivalent (Cloud SQL). State is **NOT** automatically replicated AWS↔GCP. Documents written to AWS S3 in the hour before the outage are not in GCS.
   - For audit: events written in that window survive on the (now-unreachable) AWS side; they will reconcile back when AWS recovers.
   - For documents: customers who uploaded in the hour before the outage will need to re-upload. **Disclosed up-front** in the demo's architecture doc.
4. Verify from a clean browser session: `https://api.sentinelrag.example.com/api/v1/health` returns 200 served by GCP.

**Data loss expected**
- Anything written to AWS in the unreplicated lag window.
- Cross-cloud replication (active-active or async sync) is a Phase 9 enhancement.

**Post-failover**
- Run k6 baseline against the GCP environment to confirm the resilience hypotheses still hold there.
- When AWS recovers, decide whether to fail back (planned) or stay on GCP. The Phase 8 stance is **stay on whichever is currently healthy**; don't fail back during the same incident window.

---

### S7. EKS cluster destroyed / unrecoverable

**Symptoms**
- EKS API endpoint unreachable; `kubectl get nodes` errors with `Unable to connect`.
- AWS console shows the cluster in `DELETING` or `FAILED`.

**Recovery**
1. Re-provision via Terraform: `cd infra/terraform/aws/environments/dev && terraform apply -target=module.eks`. Takes ~15 min.
2. Re-install cluster bootstrap charts (Phase 7 Slice 3): ArgoCD, External Secrets Operator, Temporal, AWS Load Balancer Controller, cert-manager.
3. ArgoCD picks up the SentinelRAG Application (since Git is the SoT) and re-applies the chart. Within 5 min, all workloads are back, pulled images from GHCR, mounted secrets via ESO, connected to the (untouched) RDS instance.

**Data loss expected**
- Zero. Cluster is stateless; data plane (RDS, S3, ElastiCache) is unaffected.

---

### S8. Secrets Manager / Secret Manager corruption

**Symptoms**
- ESO logs `failed to sync secret` for one or more SentinelRAG secrets.
- New pods crash-loop with `KEYCLOAK_ISSUER_URL not set` (or similar).

**Recovery**
1. Versioned secrets: `aws secretsmanager list-secret-version-ids --secret-id sentinelrag-dev/api` shows previous versions.
2. Roll back: `aws secretsmanager update-secret-version-stage --secret-id sentinelrag-dev/api --version-stage AWSCURRENT --move-to-version-id <prior-version-id>`.
3. If all versions are corrupt, the canonical source for non-rotatable secrets (Keycloak issuer URL, etc.) is the Terraform code in `environments/dev/main.tf`. For **rotatable** secrets (master DB password, OAuth client secret) the canonical source is the upstream system (RDS console, Keycloak admin) — re-mint and re-write.

---

## Backup verification

A daily CI job (`.github/workflows/dr-backup-verify.yml`) runs `scripts/dr/verify-backups-aws.sh` and `scripts/dr/verify-backups-gcp.sh`, asserting:

- RDS / Cloud SQL: most recent automated snapshot is < 26 h old.
- S3 / GCS documents bucket: versioning is `Enabled`.
- S3 audit bucket: Object Lock configuration shows `COMPLIANCE`, retention years > 0.
- GCS audit bucket: retention policy is `is_locked: true`, retention period > 0.

The job posts to `#sentinelrag-oncall` Slack on failure (when `SLACK_WEBHOOK` is configured) and uploads the JSON output as an artifact for trend tracking.

## DR drills

| Drill | Frequency | Scope |
|---|---|---|
| Restore RDS from snapshot | Quarterly | Dev environment; measure RTO; confirm ESO + alembic catch up |
| Object-version restore | Quarterly | Pick a random document, soft-delete, restore from version |
| GCP failover | Semi-annually | DNS cut-over to the GCP mirror, run k6 baseline against it, cut back |
| Secrets Manager rollback | Semi-annually | Rotate a secret, prove rollback brings traffic back |
| Full chaos game-day | Quarterly | Run `infra/chaos/workflows/game-day.yaml` + k6 baseline; assert all six experiment hypotheses hold |

Each drill writes a one-pager to `docs/operations/dr-drills/YYYY-MM-DD-<scope>.md` documenting: actual RTO, surprises, follow-up actions. (Directory created on first drill.)

## Escalation

**Tier 1 — on-call engineer.** Reads this runbook end-to-end, executes the recovery, files the incident.

**Tier 2 — incident commander.** Pages when:
- Multiple scenarios overlap (e.g. region outage + audit bucket policy edit).
- Recovery procedure produces unexpected state (snapshot restore fails, ArgoCD won't reconcile).
- RTO budget exceeded.

**Tier 3 — design review.** A drill or real incident exposed a gap in the runbook itself. File an issue, link the incident, schedule the runbook revision.

## Cross-references

- ADR-0016 — audit dual-write to Postgres + immutable object storage
- ADR-0023 — Helm chart shape (the migration job hook the recovery procedures invoke)
- ADR-0024 — Terraform layout (the modules the recovery procedures `apply -target` against)
- ADR-0026 — OpenSearch reintroduction (drift reconciliation; after a Postgres restore the OS index reconciles via daily Schedule)
- ADR-0027 — load + chaos testing (the experiment hypotheses align with the scenarios in this runbook)
- ADR-0028 — DR strategy + RPO/RTO commitments
