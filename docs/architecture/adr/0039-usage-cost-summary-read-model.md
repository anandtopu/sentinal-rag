# ADR-0039: Usage / cost summary read-model (`GET /usage/summary`)

- **Status:** Accepted
- **Date:** 2026-05-20
- **Deciders:** architect, solo maintainer
- **Tags:** api, cost, billing, read-model, frontend

## Context

Sibling to [ADR-0038](0038-metrics-summary-read-model.md). The v0.6 console
has a topbar `cost mtd` chip and a dashboard `Cost · MTD` tile that still
render `—` ([BACKLOG.md](../BACKLOG.md) **B10 item #2**). The design mock
shows `$184.20 · 68% of $270 budget` with a daily sparkline — i.e. spend,
budget context, and a trend.

The data exists. Every LLM call double-enters into `usage_records` per the
cost pillar ([ADR-0022](0022-cost-budgets-soft-hard-caps.md)):
`total_cost_usd NUMERIC(12,6)`, `tenant_id`, `created_at` (partition key,
indexed `(tenant_id, created_at)`), `usage_type`, `model_name`, tokens. Budget
windows + limits live in `tenant_budgets`, and `TenantBudgetRepository`
already exposes `get_active(tenant_id)` and `period_spend(tenant_id, start,
end)` (a partition-pruned `SUM(total_cost_usd)`). This is a read-model over
existing rows — no new write path.

The one decision with real consequences is **what "MTD" means**: a fixed
calendar month, or the active budget's period? Budgets are not guaranteed to
be calendar-aligned (`tenant_budgets.current_period_start/end`, `period_type`
can be week/month/custom), and the design's "% of budget" is only meaningful
against the budget's own window.

## Decision

Add `GET /api/v1/usage/summary` that aggregates `usage_records` **in
Postgres** through the RLS-bound session, reusing the established read-model
pattern from ADR-0038 (Postgres now, Prometheus/warehouse later as an
internal swap; per-tenant via RLS; cost serialized as `float`).

### Period is budget-aware, with a calendar-month fallback

- **Active budget exists** → the period is the budget's window: `since =
  current_period_start`, `until = now()` (clamped to `current_period_end`).
  `budget_utilization_pct = total_spend / limit_usd * 100`. This makes the
  dashboard's "X% of $limit" honest against the budget the tenant is actually
  measured by. `period = "budget"`.
- **No active budget** → fall back to **calendar month-to-date (UTC)**:
  `since = first day of current month 00:00Z`, `until = now()`, `budget =
  null`, `budget_utilization_pct = null`. `period = "month-to-date"`.

The frontend reads `total_cost_usd` for the chip/tile, `budget_utilization_pct`
+ `budget.limit_usd` for the "% of budget" sub, and `series` for the sparkline.

### Source of truth: `usage_records`, not `query_sessions.total_cost_usd`

Spend is summed from `usage_records` (the double-entry ledger), not from
`query_sessions.total_cost_usd`. `usage_records` captures embedding + rerank +
evaluation cost, not just generation, so it's the complete bill; ADR-0022
already makes it the cost system of record.

### Reuse + additions

- Reuse `TenantBudgetRepository.get_active` and `.period_spend`.
- Add `UsageRecordRepository.summarize(since, until)` (total cost + tokens +
  record count) and `.daily_series(since, until)` (per-UTC-day cost), both
  raw SQL filtered on `created_at` for partition pruning — raw SQL stays in
  the repository, matching that file's note.
- `UsageService(db).summarize(tenant_id)` orchestrates period selection,
  aggregation, and gap-fills the daily series (empty days → `cost_usd: 0`) so
  the sparkline doesn't connect across gaps.
- Schema `apps/api/app/schemas/usage.py` (extends `APIModel`), route
  `apps/api/app/api/v1/routes/usage.py`, registered in `router.py`.

### Auth

Reuse `queries:execute` (consistent with ADR-0038; same console surfaces).
`billing:read` is listed in the design doc's permission set but is **not
seeded or checked** anywhere in code today — minting/seeding it is deferred
to the day a billing-only role exists, exactly as ADR-0038 deferred
`metrics:read`. RLS scopes `usage_records` + `tenant_budgets` to the tenant.

### No server-side cache in v1

Same reasoning as ADR-0038: one partition-pruned scan + one budget row read,
and the frontend memoizes via TanStack Query. A memo is a later optimization.

## Consequences

### Positive

- The cost chip + tile show **real** per-tenant spend and a budget-honest
  utilization %, completing the cost-pillar's "observed before optimized"
  story end to end (write path → ledger → console).
- Zero new data plane; reuses the partition-pruned `period_spend` path and
  the `(tenant_id, created_at)` index that already exists for `usage_records`
  (so unlike the metrics endpoint, no index follow-up is owed here).
- Budget-period alignment means the dashboard % matches what the budget gate
  (`CostService.check_budget`) actually enforces — one definition of "spend
  this period", not two.

### Negative

- Two notions of period (budget vs calendar MTD) the client must not
  conflate; the response carries an explicit `period` discriminator so the UI
  can label it correctly.
- Calendar-month fallback is UTC-fixed; a tenant in another timezone sees
  month boundaries in UTC. Acceptable for v1; a tenant-timezone refinement is
  a later nicety.

### Neutral

- Adds a `/usage` route prefix and a `UsageSummary` response model. No RBAC
  migration (reuses `queries:execute`).
- The eventual full "Usage" page (per-model / per-usage_type breakdowns,
  CSV export) can extend this same endpoint or add siblings; out of scope for
  B10 #2, which is just the chip + tile + sparkline.

## Alternatives considered

### Option A — Budget-aware period with calendar fallback (this)
See above. Makes utilization meaningful; reuses the budget's own window.

### Option B — Calendar month-to-date only
Always sum the current calendar month.
- **Pros:** One simple rule; no branch.
- **Cons:** When a budget's period isn't a calendar month (week / rolling /
  mid-month start), "% of $limit" computed against a calendar month is
  misleading — it can show >100% or <actual against the wrong denominator.
- **Rejected because:** the design explicitly shows "% of budget"; that
  number is only correct against the budget's own window.

### Option C — Sum `query_sessions.total_cost_usd`
- **Pros:** One table; `query_sessions` is already aggregated for ADR-0038.
- **Cons:** Misses embedding / rerank / evaluation spend; diverges from the
  ADR-0022 cost ledger; two different "cost" numbers in the app.
- **Rejected because:** `usage_records` is the cost system of record.

## Trade-off summary

| Dimension | Budget-aware (this) | Calendar-only | query_sessions sum |
|---|---|---|---|
| "% of budget" correctness | Correct (budget window) | Wrong off-calendar | Correct but incomplete spend |
| Completeness of spend | Full ledger | Full ledger | Generation only |
| Source-of-truth alignment | ADR-0022 ledger | ADR-0022 ledger | Diverges |
| Complexity | One branch | None | None |

## Notes on the design docs

`Enterprise_RAG_Database_Design.md` lists `billing:read` in the permission
set; this ADR does **not** seed it (reuses `queries:execute`) — recorded so a
future agent doesn't assume the permission is wired. No other override.

## References

- [ADR-0038](0038-metrics-summary-read-model.md) — the metrics read-model
  sibling; same Postgres-now / Prometheus-later, RLS-scoped pattern
- [ADR-0022](0022-cost-budgets-soft-hard-caps.md) — `usage_records` ledger +
  `tenant_budgets` + `CostService` reused here
- [BACKLOG.md](../BACKLOG.md) B10 (item #2 implemented by this ADR)
- `apps/api/app/db/repositories/{usage_records,budgets}.py` — the tables aggregated
