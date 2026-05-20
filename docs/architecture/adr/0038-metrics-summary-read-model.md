# ADR-0038: Operational metrics summary read-model (`GET /metrics/summary`)

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** architect, solo maintainer
- **Tags:** api, observability, metrics, read-model, frontend

## Context

The v0.6 frontend console redesign (Phase 5, 2026-05-20) added two
operator-signal surfaces that have no backing endpoint:

- The **topbar ops strip** — `p95` latency and `err 1h` chips
  (`apps/frontend/src/components/layout/topbar.tsx`), shown on every page.
- The **dashboard p95-latency tile + sparkline**
  (`apps/frontend/src/app/dashboard/page.tsx`).

Per the redesign's "wire real, degrade honestly" stance they currently
render `—` placeholders. [BACKLOG.md](../BACKLOG.md) **B10 item #1** is the
work to give them a real source. This ADR records how.

The data already exists. `query_sessions` persists one row per query with
`tenant_id`, `status` (`running` → terminal `completed` / `abstained` /
`failed`), `latency_ms`, `total_cost_usd`, and `created_at` (see
`apps/api/app/db/repositories/query_sessions.py`). The table is tenant-owned
and carries an RLS policy like every other tenant table (pillar #2). No new
data needs to be written — this is purely a **read-model** over rows the
orchestrator already commits.

Forces:

- **No metrics store yet.** Prometheus + OTel meters exist in code
  (`sentinelrag_shared.telemetry.meters`) but there is no running
  Prometheus to query — that stack is [BACKLOG.md](../BACKLOG.md) **B1**
  (homelab observability), not yet deployed.
- **Tenant scoping is mandatory.** A tenant must only ever see its own
  query metrics. RLS already enforces this on `query_sessions`.
- **The frontend wants two shapes from one endpoint:** scalar summary
  (p95, error rate) for chips/tiles, and a short time-bucketed series for
  the sparkline.
- **Demo scale.** Single-digit-to-low-thousands of `query_sessions` rows
  per tenant. Exact aggregation in Postgres is cheap; approximate
  histograms are unnecessary.

## Decision

Add a **new read-only endpoint** `GET /api/v1/metrics/summary` that
aggregates `query_sessions` **in Postgres** through the RLS-bound request
session. Prometheus is explicitly *not* the v1 source.

### Backing store: Postgres now, Prometheus later (internal swap)

The endpoint computes percentiles and rates with a SQL aggregate over
`query_sessions`. When B1 lands and a Prometheus instance is reachable,
`MetricsService` can switch to range-querying Prometheus **without changing
the response contract** — the swap is internal to the service. The contract
is the stable surface; the backing store is an implementation detail.

This is the deciding factor: choosing Postgres now is **reversible** (swap
the service internals later) while shipping nothing until B1 is **not** — it
leaves the redesigned UI permanently dark on a stack component that is
itself deferred.

### Window parameter

`window` query param, allow-listed to `1h | 24h | 7d` (default `24h`). Each
window fixes its own bucket grain for the series so the sparkline always has
a sensible number of points:

| window | lookback | bucket grain | buckets |
|---|---|---|---|
| `1h` | 1 hour | 5 minutes | 12 |
| `24h` | 24 hours | 1 hour | 24 |
| `7d` | 7 days | 1 day | 7 |

The topbar calls `window=1h` (so both `p95` and `err 1h` describe the same
hour); the dashboard calls `window=24h`. A closed allow-list (not an
arbitrary duration string) keeps the bucket-grain mapping total and the SQL
parameter space small.

### Percentile computation

Exact percentiles via Postgres
`percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY latency_ms)`
over rows in-window with `latency_ms IS NOT NULL`. No approximate t-digest /
HDR histogram — at demo scale exactness is free and avoids a dependency.
Per-bucket series values use the same `percentile_cont(0.95)` grouped by
`date_bin(:grain, created_at, :origin)` (Postgres 14+; we run PG16).

### Rates and counts

Over terminal rows in-window (`status <> 'running'`):

- `total_queries` = count of terminal rows.
- `error_rate` = `failed / total_queries` (abstain is **not** an error).
- `abstain_rate` = `abstained / total_queries`.
- `queries_per_min` = `total_queries / window_minutes` (coarse volume signal).

Empty window → `total_queries: 0`, rates `0.0`, percentiles `null`, and an
all-zero (gap-filled) series. The frontend already treats `null`/absent as
its `—` state, so an empty tenant degrades cleanly.

### Gap-filled series

`MetricsService` generates the expected bucket boundaries in Python from
`since`/`until` and left-joins the grouped SQL result, so the series is
continuous (empty buckets become `queries: 0, p95_latency_ms: null`) and the
sparkline doesn't lie about gaps by connecting across them. Generating
boundaries in Python keeps the SQL a single plain `GROUP BY` rather than a
`generate_series` join.

### RLS / RBAC

- **Tenant scoping** rides on the existing `get_db` dependency, which issues
  `SELECT set_config('app.current_tenant_id', …, true)` per request
  (`apps/api/app/db/session.py`). The aggregate `SELECT … FROM
  query_sessions` is therefore auto-filtered to the caller's tenant by RLS
  (pillar #2) — there is no app-level `WHERE tenant_id =` needed, though the
  service still runs inside that bound session as defense-in-depth.
- **Permission:** reuse the existing seeded `queries:execute` permission
  rather than minting a new `metrics:read`. Metrics summarize the caller's
  own query activity; the surfaces that show them (playground topbar,
  dashboard) already sit behind roles that hold `queries:execute`. A new
  permission would need a seed + role-grant change for zero practical
  gain today. If an ops-only "viewer" role (dashboard but no execute) is
  ever introduced, split out `metrics:read` then — a one-line route change.

### No server-side cache in v1

The aggregate is one or two indexed scans per call and the frontend already
memoizes via TanStack Query (`staleTime: 30s`). A Redis/`Cache-Control`
memo is a later optimization, noted not built, to keep the first cut a thin
read path.

### Where the code lives (matches existing conventions)

- **Schema:** `apps/api/app/schemas/metrics.py` — `MetricsSummary`,
  `LatencyPercentiles`, `MetricsBucket`, all extending `APIModel`
  (`app/schemas/common.py`). **Not** in
  `packages/shared/python/sentinelrag_shared/contracts/` — that package is
  for cross-service/Temporal messages (ADR-0009); this is an API-only
  response.
- **Aggregation SQL:** new methods on `QuerySessionRepository`
  (`app/db/repositories/query_sessions.py`) — keeps raw SQL in the
  repository layer per that file's stated convention.
- **Service:** `apps/api/app/services/metrics_service.py` —
  `MetricsService(db).summarize(window=...)`, mirroring `EvaluationService`'s
  `__init__(self, db)` + composed-repository shape.
- **Route:** `apps/api/app/api/v1/routes/metrics.py` —
  `GET /metrics/summary`, registered in `app/api/v1/router.py`.
- **Frontend:** `api.getMetricsSummary(window)` in `lib/api.ts` +
  `MetricsSummary` types in `lib/api-types.ts`, consumed by `topbar.tsx`
  and `dashboard/page.tsx`.

## Consequences

### Positive

- The redesigned ops strip + dashboard latency tile light up with **real,
  exact** per-tenant numbers — no fabricated values, consistent with
  ADR-0029's no-hand-written-numbers rule.
- Zero new data plane: read-only over existing rows; no migration to write
  metrics, no new write path, no audit/cost-pillar impact.
- Tenant isolation is automatic (RLS), so the metrics endpoint can't leak
  cross-tenant signal even if the app-level filter were forgotten.
- The Postgres→Prometheus swap is contained behind `MetricsService`; the
  contract clients depend on doesn't move.

### Negative

- An unindexed window scan of `query_sessions` grows linearly with a
  tenant's query history. At demo scale this is negligible; at real scale a
  composite index `query_sessions(tenant_id, created_at)` (or a rollup
  table) is wanted. **Deferred**, not added here, because a hand-written
  Alembic index migration can't be applied/verified without a live Postgres
  (integration tests are Docker-blocked on the current host). Recorded as a
  follow-up.
- Two windows = two endpoint calls per page load (topbar 1h, dashboard
  24h). Acceptable — both are cached client-side and cheap server-side.
- Exact `percentile_cont` sorts the in-window latencies; fine at demo scale,
  but it's the first thing to replace if a tenant accumulates millions of
  sessions (→ Prometheus histogram, the documented swap).

### Neutral

- Adds a new route prefix `/metrics`. No RBAC migration (reuses
  `queries:execute`).
- The OpenAPI spec gains the `MetricsSummary` response model.
- The endpoint is per-tenant operational metrics, distinct from the
  cardinality-disciplined OTel **system** meters in
  `sentinelrag_shared.telemetry.meters` (those are for Prometheus/Grafana
  scraping; this is for the in-app console). The two coexist.

## Alternatives considered

### Option A — Aggregate `query_sessions` in Postgres (this)
See above. Reversible, zero new data plane, exact at demo scale.

### Option B — Proxy Prometheus / OTel range queries
Query a deployed Prometheus for `histogram_quantile(...)` over the
`sentinelrag_stage_latency_ms` + `sentinelrag_queries_total` meters.
- **Pros:** Purpose-built for percentiles-over-time; scales past Postgres;
  reuses meters already emitted.
- **Cons:** Requires a running Prometheus — that's **B1**, not yet
  deployed. The OTel counters are deliberately cardinality-disciplined
  (no `tenant_id` on high-volume series, per Phase 6), so they **cannot**
  produce the *per-tenant* breakdown the multi-tenant console requires
  without adding tenant labels and accepting the cardinality blow-up.
- **Rejected because:** it blocks on undeployed infra *and* the existing
  meters can't answer the per-tenant question. This is the documented
  future swap for the **system-wide** view, not the per-tenant console view.

### Option C — Materialized rollup table refreshed by a Temporal schedule
A `query_metrics_hourly` table aggregated by a recurring workflow.
- **Pros:** O(1) reads; no scan on the hot path.
- **Cons:** A new write path, a new schedule, staleness windows, and a
  migration — all to optimize a read that is currently cheap.
- **Rejected because:** premature optimization. Revisit if/when the
  unindexed scan (see Negative) actually hurts; the rollup is the natural
  next step after the simple index.

### Option D — New `metrics:read` permission
- **Pros:** Cleaner separation if an ops-only role appears.
- **Cons:** Needs a permission seed + role-grant change for no behavioral
  difference today (the only roles that view these surfaces already hold
  `queries:execute`).
- **Rejected because:** adds RBAC surface with no current consumer. Split
  it out the day an execute-less viewer role exists.

## Trade-off summary

| Dimension | Postgres aggregate (this) | Prometheus proxy | Rollup table |
|---|---|---|---|
| Needs undeployed infra | No | Yes (B1) | No |
| Per-tenant breakdown | Native (RLS) | Needs tenant labels (cardinality cost) | Native |
| Read cost at scale | Window scan | O(1) | O(1) |
| New write path | None | None | Schedule + table + migration |
| Exactness | Exact | Approx (histogram buckets) | Exact (as-of refresh) |
| Reversibility | High (swap service internals) | — | Medium |

## Notes on the design docs

`Enterprise_RAG_PRD.md` calls for an operations dashboard; this ADR adds the
first real metrics endpoint behind it. No design-doc override — this is
additive. The other B10 panels (usage/cost summary, query-history feed, eval
per-metric medians) are separate items and out of scope here.

## References

- [BACKLOG.md](../BACKLOG.md) **B10** (item #1 implemented by this ADR),
  **B1** (observability stack — the future Prometheus source)
- [ADR-0009](0009-rest-not-grpc.md) — REST + Pydantic; contracts package
  scope (why the response schema is API-only, not a cross-service contract)
- [ADR-0022](0022-cost-budgets-soft-hard-caps.md) — `usage_records` /
  `total_cost_usd`; the cost-summary sibling endpoint (B10 #2) will build on it
- Phase 6 OTel meters in `sentinelrag_shared.telemetry.meters` — the
  system-wide, cardinality-disciplined counterpart to this per-tenant view
- `apps/api/app/db/repositories/query_sessions.py` — the table aggregated
- [Postgres `percentile_cont`](https://www.postgresql.org/docs/current/functions-aggregate.html#FUNCTIONS-ORDEREDSET-TABLE)
  / [`date_bin`](https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-BIN)
