# SentinelRAG — backlog

> Free-floating deferred work that doesn't sit cleanly inside a phase row
> in [`PHASE_PLAN.md`](PHASE_PLAN.md) or a remediation slice in
> [`REMEDIATION_PLAN.md`](REMEDIATION_PLAN.md). Tracked here so a future
> session can pick any item up without re-deriving the context.
>
> Each item: **scope · why deferred · gating signal to pick it up · rough size**.

## Active backlog

### B1 — Homelab observability stack
- **Scope:** Add an `observability` namespace to the K3s homelab with OTel
  Collector → Tempo (traces) + Prometheus (metrics) + Loki (logs) +
  Grafana. Replace the unreachable `OTEL_EXPORTER_OTLP_ENDPOINT` placeholder
  in `infra/helm/sentinelrag/values-homelab.yaml` with the in-cluster
  collector URL. Provision Grafana datasources + the four dashboards
  already in `infra/observability/grafana/dashboards/`.
- **Why deferred:** First homelab cut prioritized "app runs and login
  works." Observability adds ~2 GB of memory and an hour of bootstrap
  time, neither of which the v1 demo needs.
- **Gate:** Homelab v1 deploy is green and stable; user wants the trace /
  dashboard story to be part of the 5-minute demo video.
- **Size:** 1–2 sessions. Likely candidate: another `infra/bootstrap/`
  values overlay + an extension to `bootstrap-homelab.sh`.

### B2 — Homelab HTTPS via cert-manager
- **Scope:** Switch Traefik ingress from HTTP-only to HTTPS. Install
  cert-manager into the homelab, issue a self-signed CA, mint certs for
  the three `*.sentinelrag.local` hostnames, distribute the CA to the
  build host. Update `values-homelab.yaml` ingress annotations to drop
  the `entrypoints: web` override and let Traefik use `websecure`.
- **Why deferred:** Self-signed certs on `.local` hostnames produce
  browser warnings that distract from the demo. HTTP is fine for a
  LAN-only homelab.
- **Gate:** Either the demo needs an HTTPS shot, or a feature (NextAuth
  cookie security flag, OAuth callback) breaks under plain HTTP.
- **Size:** 1 session.

### B3 — ArgoCD-on-homelab GitOps
- **Scope:** Install ArgoCD in the homelab, register the SentinelRAG
  Helm chart + the homelab values overlay as an `Application`, switch
  `deploy-homelab.sh` to `argocd app sync` instead of `helm upgrade`.
  Wire the existing GHCR build pipeline so ArgoCD Image Updater rolls
  tags forward on push.
- **Why deferred:** Homelab v1 uses straight `helm upgrade --install`
  to stay legible for the runbook reader. Adding ArgoCD doubles the
  surface area and isn't a recruiter-facing differentiator (the cloud
  Argo path already proves the GitOps story).
- **Gate:** User wants the homelab to drift-test the ArgoCD path
  end-to-end, OR the cloud Argo path develops a bug only visible on
  bare metal.
- **Size:** 1–2 sessions. Bootstrap manifests already exist at
  `infra/bootstrap/argocd/`.

### B4 — OpenSearch on homelab (parity drill)
- **Scope:** Behind the `keyword-backend-opensearch` Unleash flag, run
  an OpenSearch instance in the homelab cluster. Used to validate that
  the `KeywordSearch` interface's two implementations produce the same
  RBAC-filtered results on identical corpora.
- **Why deferred:** ADR-0026 makes Postgres FTS the always-on default
  and gates OpenSearch behind a flag specifically to keep the default
  footprint small. Wiring up OpenSearch on a 3-node homelab is
  ~3 GB extra memory for a "scale story" demo we don't need yet.
- **Gate:** A demo question asks "what changes when you outgrow Postgres
  FTS," and we'd rather show it than describe it.
- **Size:** 1 session. The chart already supports OpenSearch via the
  cloud overlays — homelab values just need the flag flipped on plus a
  StatefulSet for the OpenSearch instance.

### B5 — Homelab disaster-recovery drill
- **Scope:** Wire the daily backup verifier
  (`.github/workflows/dr-backup-verify.yml` — currently
  AWS/GCP-only) to also exercise the homelab Postgres + MinIO PVCs.
  Run the 8 failure scenarios in `docs/operations/runbooks/disaster-recovery.md`
  against the homelab to record real RTO numbers.
- **Why deferred:** PROGRESS.md called out "drill-recorded RTO numbers
  in DR runbook" as a blocker for Phase 8 close-out. Was tied to AWS
  deploy because that's where the verifier ran. Homelab is a cheaper
  drill venue now that it exists.
- **Gate:** Homelab v1 stable; user wants the DR runbook to ship with
  real numbers, not the placeholder table.
- **Size:** 1 session.

### B6 — First-live AWS deploy (paused, not cancelled)
- **Scope:** The full pre-flight + apply track from
  [`handoff/2026-05-17-deploy-prep.md`](handoff/2026-05-17-deploy-prep.md):
  `aws configure`, install `jq`, review-only walkthrough of
  `infra/terraform/aws/`, drift check of `deployment-aws.md` against the
  post-R4/R6 chart (retrieval workload + `RETRIEVAL_SERVICE_TOKEN`
  secret + R6 startup guard), produce a pre-flight checklist, then user
  fires `terraform apply` + `helm install` against their AWS account.
- **Why deferred:** User explicitly back-burnered AWS behind the K3s
  homelab on 2026-05-18 (this session). Homelab proves the chart works
  on bare metal before paying for cloud apply.
- **Gate:** Homelab v1 stable + user has bandwidth + cost acceptance
  for the ~$200-300/mo idle EKS+RDS+ElastiCache+NAT footprint.
- **Size:** 1–2 sessions (review + checklist), then user-driven apply.
- **Resume from:** [`handoff/2026-05-17-deploy-prep.md`](handoff/2026-05-17-deploy-prep.md).

### B7 — 5-minute demo video
- **Scope:** Record the recruiter-grade demo: tenant context →
  document upload → retrieval with trace → cited answer → audit log →
  cost dashboard.
- **Why deferred:** Gates on having a real deployed environment to
  demo against. Homelab v1 unblocks this; AWS deploy (B6) is the
  alternate path.
- **Gate:** Either homelab v1 + observability (B1) green, OR AWS
  deploy (B6) green.
- **Size:** 1 session (record + edit).

### B8 — Real eval + cost numbers
- **Scope:** Run `tests/performance/evals/compare.py` against the
  deployed environment and the cost-report renderer against real
  `usage_records`, overwriting the placeholder tables in
  `docs/operations/eval-report.md` and `docs/operations/cost-report.md`.
- **Why deferred:** Gates on a deployed environment + a non-trivial
  corpus ingested + a representative query set run. Per ADR-0029, the
  placeholder reports are intentionally regenerated on every harness
  run — never committed by hand.
- **Gate:** Homelab v1 + B1 (observability) so we can attach traces to
  the numbers, OR AWS deploy + sustained traffic.
- **Size:** 1 session (harness already exists; just point + shoot).

### B9 — Episodic AWS demo wrapper (snapshot & destroy)
- **Scope:** Add `make aws-up` / `make aws-down` targets that implement
  the "Snapshot & Destroy" pattern (Option A from the 2026-05-18 cost
  analysis): destroy `module.eks` + `module.redis` between sessions,
  preserve state via an RDS snapshot lifecycle, restore on resume.
  Concrete deliverables:
  1. `Makefile` targets `aws-up` / `aws-down` driving
     `terraform apply -target=...` and `aws rds create-db-snapshot` /
     `restore-db-instance-from-db-snapshot`.
  2. Snapshot rotation policy (keep last N, prune older) wrapped in a
     small script under `scripts/aws/`.
  3. Keycloak realm export-to-S3 hook on shutdown, import-from-S3 on
     startup — required because Keycloak is in-cluster and dies with
     EKS. Alternative: move Keycloak's Postgres to the managed RDS
     instance as a second database (one ADR's worth of change) so the
     realm state is snapshotted along with the app DB.
  4. Resume-time optimization: pre-pull image step in `aws-up` so the
     first cluster start isn't 5+ min of `ImagePulling`.
  5. Documentation update in `docs/operations/runbooks/deployment-aws.md`
     calling out the episodic-vs-steady-state cost split.
- **Why deferred:** Pure cost/operational ergonomics — depends on B6
  (first AWS apply) so the snapshot-restore path can be tested against
  a real RDS instance with real schema applied. Building this before
  B6 is speculative.
- **Gate:** B6 complete (first AWS apply done, real Terraform state
  exists, real RDS instance with applied migrations available to
  snapshot).
- **Size:** 1 session post-B6. Estimated steady-state cost after this
  ships: **~$8-13/mo** for 4× 2-hour demos/month (vs. ~$328/mo always-on
  per the 2026-05-18 analysis).
- **Resume from:** the cost-analysis conversation in the 2026-05-19
  session — Option A in the "low cost AWS deploy" answer captures the
  Makefile shape, snapshot logic, and add-ons (Karpenter pre-pull,
  CloudFront fallback page).

## How to use this file

- New deferred work goes here as a new `### Bn — <scope>` block.
- Picked-up work is **moved out** (to PHASE_PLAN row, a REMEDIATION
  slice, or a handoff doc), not just struck through — keep the backlog
  list of *open* items short.
- If an item changes shape, edit it in place. Don't append revisions.
- The `**Gate**` line is the most important field — it tells future-you
  whether the precondition has been met yet.
