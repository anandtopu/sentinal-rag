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

### B10 — Backend APIs for the redesigned console's live-signal panels
- **Scope:** The v0.6 frontend redesign wires every panel to real data and
  degrades honestly (`—` / empty state) where no endpoint exists. Several
  signature panels are therefore rendered but dark. Add the backing APIs so
  they light up. Each endpoint maps to a specific, already-wired panel:
  1. ✅ **Metrics summary** — **Shipped 2026-05-20 ([ADR-0038](adr/0038-metrics-summary-read-model.md)).**
     `GET /api/v1/metrics/summary?window=1h|24h|7d` aggregates `query_sessions`
     in Postgres (RLS-scoped) → percentiles + error/abstain rates + gap-filled
     series. Lights up the topbar `p95` / `err 1h` chips and the dashboard
     `Queries · 24h` + `p95 latency` tiles with sparklines. Prometheus proxy
     remains the documented future swap (gated on B1). Code:
     `apps/api/app/{schemas/metrics.py,services/metrics_service.py,api/v1/routes/metrics.py}`,
     `QuerySessionRepository.{window,bucket}_aggregate`; consumed by
     `topbar.tsx` + `dashboard/page.tsx`.
  2. ✅ **Usage / cost summary** — **Shipped 2026-05-20 ([ADR-0039](adr/0039-usage-cost-summary-read-model.md)).**
     `GET /api/v1/usage/summary` aggregates `usage_records` + `tenant_budgets`
     (RLS-scoped) → spend over the active budget period (or calendar
     month-to-date), budget context + utilization %, and a gap-filled daily
     cost series. Lights up the topbar `cost mtd` chip (tone by utilization)
     and the dashboard `Cost · MTD` tile (`X% of $limit budget` + sparkline).
     Code: `apps/api/app/{schemas/usage.py,services/usage_service.py,api/v1/routes/usage.py}`,
     `UsageRecordRepository.{summarize,daily_series}` (+ reuses
     `TenantBudgetRepository.get_active`/`period_spend`); consumed by
     `topbar.tsx` + `dashboard/page.tsx`.
  3. ✅ **Query-history feed** — **Shipped 2026-05-20.** `GET /api/v1/query`
     (paginated, RLS-scoped) lists recent `query_sessions` LEFT JOINed to
     `generated_answers` (grounding score + model). Lights up the dashboard
     "Recent queries" card (rows: id, time-ago, query, grounding badge,
     latency, abstain/failed flags). A conventional list endpoint following the
     ADR-0038 read-model pattern + the existing collections/documents list
     shape — no separate ADR. Code:
     `QuerySessionRepository.list_recent`, `QueryHistoryService`,
     `QuerySessionListItem` schema, `GET /query` in `routes/query.py`;
     consumed by `dashboard/page.tsx`.
  4. ✅ **Eval-run summaries** — **Shipped 2026-05-20 ([ADR-0040](adr/0040-evaluation-summary-batch-read.md)).**
     Investigation found `GET /eval/runs/{id}` *already* returns real
     per-metric averages, aggregated live from per-case `evaluation_scores`
     via `aggregate_for_run` — so they were never actually missing. The real
     gap was the frontend's N+1 fan-out (one `getEvalRun` per run, each
     404-fragile). Fixed by the batch read `GET /api/v1/eval/runs?include=summary`
     (one `GROUP BY` query via `aggregate_for_runs` + `summaries_for`), with
     `summary` added to `EvaluationRunRead`. The evaluations page now makes one
     call; leaderboard columns / median tiles / trend / case-outcomes populate
     with real numbers. A summary snapshot on `evaluation_runs` was
     deliberately **not** built (drift-prone, premature) — see ADR-0040 for
     the rationale and the revisit conditions.
- **Why deferred:** This was the "Extend the backend" option explicitly
  not taken during the v0.6 redesign — the chosen approach was "wire real,
  degrade gracefully," so the UI is correct and ships now; the panels are
  intentionally honest blanks rather than fabricated numbers (consistent
  with ADR-0029's no-hand-written-numbers rule). Crosses from `apps/frontend`
  into `apps/api` (+ contracts in `packages/shared/python/contracts/`).
- **Status:** ✅ **All four items shipped (2026-05-20, ADR-0038/0039/0040),
  plus the perf-index follow-up below.** The console's previously-dark panels
  (topbar p95/err/cost, dashboard vitals + recent-queries, evaluations
  leaderboard/medians/trend) all show real per-tenant data.
- **Perf follow-up (from ADR-0038):** ✅ **Shipped 2026-05-20** —
  `migrations/versions/0017_query_sessions_tenant_created_index.py` adds the
  composite `idx_query_sessions_tenant_created` on
  `query_sessions(tenant_id, created_at DESC)`, built `CONCURRENTLY` in an
  `autocommit_block` (class A per ADR-0033). Verified offline (ruff, `alembic
  heads` single head 0017→0016, `alembic upgrade --sql` emits the concurrent
  index). **Applying it against a live Postgres (`make db-upgrade`) is still
  pending** — integration/DB is Docker-blocked on the current host.

### B11 — Migration packaging mismatch (deploy blocker, latent)
- **Scope:** The canonical migration chain is the repo-root `migrations/`
  (0001→0017; `make db-*` and the full schema live here). But the deploy path
  doesn't ship it: `apps/api/Dockerfile` does `COPY apps/api/ /app/`
  (WORKDIR `/app`) and never copies repo-root `migrations/` — the image only
  carries the **stray** `apps/api/migrations/` (a separate chain whose only
  revision, `001_initial_schema.py`, just creates extensions). Meanwhile the
  Helm pre-upgrade Job (`infra/helm/sentinelrag/templates/migrations/job.yaml`
  + `values.yaml`) runs `cd /workspace && alembic -c migrations/alembic.ini
  upgrade head`, expecting the canonical chain at `/workspace/migrations` —
  a path the image neither creates nor populates. So a real `helm upgrade`
  would fail (`/workspace` missing) or, against the in-image config, apply
  only the extensions migration — not the schema.
- **Status:** ✅ **Shipped 2026-05-20.** `apps/api/Dockerfile` now
  `COPY migrations/ /workspace/migrations/` (build context is repo root) so the
  canonical chain lands where the Helm Job's existing `cd /workspace && alembic
  -c migrations/alembic.ini upgrade head` command looks; the pip line installs
  `psycopg[binary]` (psycopg3) since `env.py` resolves the sync URL to the
  `+psycopg` dialect (the chart supplies only `DATABASE_URL`, no
  `DATABASE_URL_SYNC`). The stray `apps/api/migrations/` + `apps/api/alembic.ini`
  were deleted (no references anywhere). Docker + Helm + Makefile now agree on
  repo-root `migrations/` as the single source of truth. Verified: `helm
  template` renders the Job against the API image with the `/workspace` command;
  `alembic heads` → single head `0017`; no dangling refs. `deployment-aws.md`
  Step 9 notes the path + failure symptoms. **Not verified against a live
  cluster** (no EKS/homelab apply on this host) — confidence is "renders +
  chain resolves," not "ran in dev EKS."

## How to use this file

- New deferred work goes here as a new `### Bn — <scope>` block.
- Picked-up work is **moved out** (to PHASE_PLAN row, a REMEDIATION
  slice, or a handoff doc), not just struck through — keep the backlog
  list of *open* items short.
- If an item changes shape, edit it in place. Don't append revisions.
- The `**Gate**` line is the most important field — it tells future-you
  whether the precondition has been met yet.
