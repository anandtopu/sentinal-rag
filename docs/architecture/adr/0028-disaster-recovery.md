# ADR-0028: Disaster recovery — RPO/RTO commitments, active-passive cross-cloud, automated backup verification

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** dr, resilience, multi-cloud, sre

## Context

Phase 8's last open item is "Disaster recovery runbook." A runbook by
itself is just prose; the actually-load-bearing decisions are:

1. **What RPO / RTO are we promising?** Stating "we recover quickly" is
   not a commitment.
2. **Active-active or active-passive across AWS ↔ GCP?** Both clouds are
   already provisioned (Phase 7 + Phase 8 Slice 1). The Helm chart is
   identical, so the platform *can* run anywhere. The question is whether
   we keep both warm with traffic, or one warm and one cold-but-deployed.
3. **How do we know the backups work?** Backups that have never been
   restored are wishes, not backups. The runbook is only credible if
   something automated proves the snapshots exist and meet retention
   policy daily.

These three questions together define what "disaster recovery" actually
*is* for SentinelRAG. The runbook at
`docs/operations/runbooks/disaster-recovery.md` is the procedural side
of this ADR; this ADR is the architectural commitment.

## Decision

### RPO / RTO commitments

| Tier | Component | RPO | RTO |
|---|---|---|---|
| 0 | Audit log | 0 (immutable, dual-write) | n/a |
| 1 | Postgres (tenants, RBAC, query state, audit mirror) | 5 min | 1 h |
| 1 | S3 / GCS documents bucket | 24 h | 2 h |
| 2 | Redis cache | n/a (cold-start tolerated) | 15 min |
| 2 | Temporal cluster | 5 min | 1 h |
| 3 | Eval results, metrics, traces | 1 h | best-effort |

**Tier 0 is the hard guarantee.** Object Lock COMPLIANCE on AWS / Locked
Retention Policy on GCS make audit objects unrecoverable-as-deleted within
the 7-year retention window — so there is no RPO to define for them. The
audit dual-write (ADR-0016) keeps Postgres + object storage in sync; if
either side is lost, the daily `AuditReconciliationWorkflow` (Phase 6.5)
backfills the survivor from the other.

**Tier 1 RPO of 5 minutes** is achievable on RDS Postgres with
point-in-time recovery + automated snapshots, on Cloud SQL with
point-in-time + automated backups. **RTO of 1 hour** is what the dev
environment can hit today; production with Multi-AZ failover targets
60–120 seconds and we'll re-state when prod ramps.

**Tier 2 — Redis and Temporal** are recoverable but slower. Redis is a
soft dependency (validated by Chaos experiment 03 in ADR-0027). Temporal
state lives in Postgres so its RPO inherits Tier 1's; what differs is
that workflow replay takes time after recovery, hence the Tier 2 RTO.

### Active-passive across AWS ↔ GCP, manual cut-over

Both clouds are deployed. AWS is active. GCP is **deployed-but-cold** —
no production traffic, but the cluster, data plane, and chart are all
there and verified by the Phase 8 GCP Slice 1 work + the daily backup
verifier.

We chose active-passive over active-active for three reasons:

1. **Cross-cloud data replication is a separate engineering project**,
   not a flag flip. RDS and Cloud SQL don't sync to each other natively.
   Going active-active means Debezium or equivalent + a conflict
   resolution model — a tier of complexity that doesn't fit Phase 8's
   scope.
2. **The customer-disclosed RPO when failing over is the AWS↔GCP
   replication lag.** With no replication, that's "everything since the
   last app-level export." We disclose this up-front: documents
   uploaded in the last hour before an AWS region outage will need to
   be re-uploaded after failover. This is honest; an active-active
   pretense would not be.
3. **Cost** — keeping a warm GCP runtime ready (idle pods + DBs) is
   cheaper than running a hot active-active mesh, by a factor of ~2 for
   our scale.

The failover procedure is in the runbook (S6). Cut-over is DNS-driven
(Route 53), takes ~5 min including propagation, and is reversible.

### Automated backup verification, daily, tracked in CI

`scripts/dr/verify-backups-aws.sh` + `scripts/dr/verify-backups-gcp.sh`
assert four invariants daily:

- RDS / Cloud SQL automated snapshot is < 26 h old.
- Documents bucket versioning is `Enabled`.
- Audit bucket Object Lock / retention policy is `COMPLIANCE` /
  `is_locked: true`.
- Audit retention period is > 0 years.

The 26-hour ceiling exceeds the 24-hour expected snapshot cadence by
one cron-skew window, so a one-off late snapshot doesn't false-page.

`.github/workflows/dr-backup-verify.yml` runs both scripts daily at
06:37 UTC (after the 03:00 RDS backup window completes) plus on PRs that
touch the verifier code. The workflow gates on repo variables
(`SENTINELRAG_AWS_ENABLED`, `SENTINELRAG_GCP_ENABLED`) so external
contributors and unconfigured forks no-op cleanly. Failure posts to
Slack via webhook (when configured) and uploads the JSON status doc as
an artifact for trend tracking.

### What we did NOT do

- **No cross-cloud data replication.** Phase 9 work, when (if) the
  RPO target tightens past 1 hour for cross-region failover.
- **No automated DR-drill workflow.** Drills are operator-initiated
  (quarterly cadence in the runbook) — automating them is a Phase 9
  polish item once we have a tagged "drill mode" toggle.
- **No backup *restore* verification** beyond the snapshot-exists check.
  Drilling restore is the quarterly drill itself; doing it daily would
  cost real RDS-restore time + dollars. The trade-off is "we know the
  snapshot exists daily; we know it actually restores quarterly."
- **No multi-region within AWS.** A regional outage drops us to GCP, not
  to a second AWS region. We accept this as the same trade-off that
  drove the GCP-mirror-as-DR-target decision in ADR-0011.

## Consequences

### Positive

- The RPO/RTO numbers are concrete, testable commitments. They map to
  scenarios in the runbook and to Chaos experiment hypotheses
  (ADR-0027), so a regression in any of them is detectable.
- The cross-cloud failover path is real (both clouds deployed) without
  the operational overhead of active-active.
- Daily automated verification means a backup-policy regression
  (someone disables versioning, RDS snapshots stop firing) gets caught
  within 24 hours, not at the next incident.

### Negative

- An AWS-region outage costs us the unreplicated lag window on data
  plane. We disclose this; it is the price of not running a sync.
- Manual DNS cut-over is a human in the loop. Automating it requires
  health-check signals we don't have on the GCP side yet (Phase 9).
- Drilling restore quarterly leaves a 90-day window where a snapshot
  could exist-but-be-corrupt and we wouldn't know. We accept this; the
  alternative (daily restore) is too expensive. Mitigation: when a real
  incident forces a restore, that becomes the drill data point.

### Neutral

- The daily verifier scripts are bash. They could be Python; bash is
  enough for the 4 assertions and AWS CLI / gcloud ergonomics.
- The DR runbook lives at `docs/operations/runbooks/` per the doc
  convention. Future runbooks (e.g. cost-overrun playbook, eval-regression
  playbook) join it there.

## Alternatives considered

### Option A — Active-active across AWS + GCP

- **Pros:** Zero RPO during a regional outage if replication is healthy.
  Recruiter-strong "we run both clouds in parallel."
- **Cons:** Cross-cloud sync is real engineering. Conflict resolution.
  Doubled cost. Operational burden.
- **Rejected because:** Phase 8 scope; can revisit in Phase 9 if scale
  demands it.

### Option B — Daily automated restore-test

- **Pros:** True backup confidence — every day proves restore works.
- **Cons:** Real cost (RDS restore-from-snapshot is ~30 min per cycle),
  test instances accumulate, false alarms when restore takes > expected.
- **Rejected because:** quarterly drills + daily snapshot-exists check
  is enough at this scale. Revisit if a snapshot-corrupt-but-exists
  incident actually happens.

### Option C — Cross-region within AWS (no GCP)

- **Pros:** Simpler than cross-cloud; AWS-native cross-region replication
  for RDS + S3 exists.
- **Cons:** Doesn't exercise the multi-cloud story (ADR-0011), which is
  a load-bearing portfolio signal. Same single-cloud blast-radius risk
  for an AWS-account-level event (compromised root credentials, billing
  shutoff).
- **Rejected because:** GCP mirror earns more recruiter signal and
  protects against more failure modes.

## Trade-off summary

| Dimension | Active-passive cross-cloud (this) | Active-active cross-cloud | Active-passive same-cloud (multi-region) |
|---|---|---|---|
| RPO during regional outage | unreplicated lag (~minutes-hours) | ~seconds | ~minutes |
| RTO | DNS cut-over (~5 min + propagation) | seamless | 5–10 min |
| Cost (idle GCP) | 1× hot AWS + ~30% cold GCP | 1× AWS + 1× GCP | 1× AWS + 30% second region |
| Engineering complexity | low (deploy both, no sync) | high (sync, conflict res) | medium |
| Multi-cloud demonstration | yes | yes | no |
| Account-level event protection | yes | yes | no |

## Notes on the design docs

`Enterprise_RAG_Deployment.md` §18 mentions "DR strategy" but doesn't
commit numbers. This ADR commits the RPO/RTO matrix and pins the
cross-cloud strategy to active-passive. The runbook at
`docs/operations/runbooks/disaster-recovery.md` is the operational
manifestation.

## References

- ADR-0011: Multi-cloud strategy (AWS primary, GCP mirror)
- ADR-0016: Audit dual-write to Postgres + immutable object storage
- ADR-0026: OpenSearch reintroduction (drift reconciliation reused for
  audit)
- ADR-0027: Load + chaos testing (the experiment hypotheses align with
  the recovery scenarios)
- `docs/operations/runbooks/disaster-recovery.md` — the procedural
  manifestation of this ADR
- AWS RDS PITR docs; Cloud SQL backup docs; S3 Object Lock; GCS retention
  policies
