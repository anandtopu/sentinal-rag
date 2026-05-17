# ADR-0033: Zero-downtime schema migration strategy

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** database, migrations, deployment, alembic, helm

## Context

[ADR-0012](0012-helm-argocd-deployment.md) commits to Helm + ArgoCD
GitOps for production rollouts. Each rollout runs the SentinelRAG
chart's pre-upgrade `alembic` Job (see `templates/migrations/job.yaml`)
that calls `alembic upgrade head` against the live database before the
new app pods receive traffic.

That works for *additive* migrations (new column NULL-able, new table,
new index `CONCURRENTLY`) — the running old pods are agnostic to the
new shape. It breaks for any of these:

- Renaming or dropping a column the old pods still read or write.
- Adding a `NOT NULL` column without a default — old pods writing
  fresh rows fail their `INSERT`.
- Changing a column's type (Postgres rewrites the table; long
  ACCESS EXCLUSIVE lock; new pods can't talk to the old schema and
  old pods can't talk to the new one).
- Renaming a table.
- Tightening a `CHECK` constraint.

The R3 + R4 work introduced enough surface area
(`generated_answers.nli_verdict`, `query_sessions.error_message`,
the planned `user_identity_map` per ADR-0032) that "we'll just be
careful" stops scaling. A documented pattern + a CI gate + a
runbook entry is the right shape.

The Helm + ArgoCD model also constrains the answer: we can't run
arbitrary code between "old pods serving" and "new pods serving" —
the migration Job runs once, before the rolling deployment kicks
off.

## Decision

Adopt the **expand → backfill → contract** pattern for every
schema change that's not purely additive-and-NULL-able. Each phase
is its own Alembic revision; each Alembic revision is a separate PR
+ deployment so the cluster sits in a consistent state between
phases.

### Migration classes

We classify every revision into one of three buckets at PR review
time. The class drives what's allowed in the pre-upgrade Job and
what coordination the PR description must call out:

| Class | Examples | Allowed in pre-upgrade Job? | Multi-deploy required? |
|---|---|---|---|
| **A — additive, safe** | new NULL-able column; new table; new index `CONCURRENTLY`; FK additions; new CHECK that the data already satisfies | Yes | No |
| **B — expand step** | new NULL-able column that will become NOT NULL after backfill; new FK to a tombstone table per ADR-0032 | Yes | Yes — paired with B' contract in a later release |
| **B' — contract step** | drop old column; flip new column to NOT NULL; drop old index; rename table | Yes (but only AFTER B's deployment is fully rolled out AND the app code reads/writes the new shape) | Yes — preceded by B |
| **C — incompatible** | type change requiring a table rewrite; rename in-place | **No** — needs maintenance window, blocked at review |

PRs adding class-C migrations are rejected by the review checklist;
they must be reshaped as expand→contract.

### Expand → backfill → contract template

For a rename of `users.email` → `users.contact_email`:

1. **Release N (B):** Alembic revision adds `contact_email`
   NULL-able. App code writes BOTH columns; reads prefer
   `contact_email` and falls back to `email`. Deploy.
2. **Backfill:** Either a one-shot SQL `UPDATE users SET contact_email
   = email WHERE contact_email IS NULL` run from the platform-admin
   session (see §"RLS interaction"), or a Temporal backfill workflow
   for tables > ~10M rows.
3. **Release N+1 (B'):** Alembic revision sets `contact_email NOT
   NULL`, drops `email`. App code reads/writes only
   `contact_email`. Deploy.

The two-PR sequence is non-negotiable; trying to land both at once
gives you exactly the broken state we're avoiding.

### What goes in the pre-upgrade Job

Anything in class A or B (additive direction). The pre-upgrade Job
runs `alembic upgrade head` against the live DB; the rolling
deployment that follows brings the new pods up against the expanded
schema. Old pods continue to function because the old shape is
still present.

Class B' migrations also run in the pre-upgrade Job, but ONLY in the
release that drops the now-unused old shape — the previous release
already moved app reads and writes to the new shape.

### Locking discipline

Even within class A, two operations need explicit `CONCURRENTLY`:

- `CREATE INDEX` on tables > ~100k rows.
- `ALTER TABLE ADD CONSTRAINT ... FOREIGN KEY` — use `NOT VALID`
  first, then `VALIDATE CONSTRAINT` in a follow-up (the validate
  step takes a shorter SHARE lock instead of ACCESS EXCLUSIVE).

`statement_timeout = 5min` is set on the migration session so a
runaway lock cannot stall every other tenant's request indefinitely.
A timeout abort is recoverable; a 30-minute table-level lock
followed by a forced kill is not.

### RLS interaction

Migrations bind a privileged session (per
`apps/api/app/db/session.py::get_admin_session`) that does NOT set
`app.current_tenant_id`. Postgres RLS policies use `current_setting('app.current_tenant_id')`
to filter rows; the admin session sees all rows.

This means migrations can `UPDATE` across tenants in a backfill —
useful when porting a column's value for every tenant in one
statement. The trade-off: a buggy migration can touch any tenant.
Mitigations:

- Migrations are reviewed line-by-line.
- The admin session is not exposed to application code; only
  Alembic + a documented set of platform-admin operations (tenant
  provisioning + the RTBF workflow per ADR-0032) use it.
- Backfill workflows that are long-running run per-tenant in a
  Temporal loop instead of a single cross-tenant `UPDATE`, so the
  blast radius of a stuck transaction is one tenant.

### CI gate

A pre-merge check walks any new revision file and reports its
class to the reviewer. Class A is auto-approved label-wise; class B
or B' triggers a "matching contract PR is in flight?" reviewer
prompt; class C blocks the merge.

The check is a Python script in `tests/migrations/classify.py`
(deferred to the implementation phase); the rules above are the
spec.

## Consequences

### Positive

- Every release continues to roll forward without a maintenance
  window — the Helm + ArgoCD GitOps story stays clean.
- The pattern is well-understood (the ecosystem calls it
  expand-contract / parallel-change). Recruiters with multi-region
  deploys in their resume will recognize it.
- The RLS-bypass surface is explicit: only the migration session
  and the platform-admin workflows escape RLS, and we have ADR
  links from each call site.

### Negative

- Renames become two PRs and two releases. Annoying for cosmetic
  renames; we accept that and don't try to optimize the rename UX.
- Long backfills (multi-hour) need a Temporal workflow instead of
  one SQL statement; one more thing to operate. Mitigated by the
  per-tenant blast-radius point.
- The class-classification check is one more thing CI runs.

### Neutral

- Many ecosystem tools (django-evolution, schemachange) bake this
  pattern in. We do it by hand with Alembic; the pattern is what
  matters, not the tool.

## Alternatives considered

### Option A — Maintenance windows for breaking changes
- **Pros:** Simple. Lots of operations teams accept it.
- **Cons:** Multi-tenant SaaS with global tenants has no good
  window. The point of GitOps is to roll any change at any time.
- **Rejected because:** kills the "deploy any commit at any time"
  property that ADR-0012 commits to.

### Option B — Blue/green deploys with full DB replay
- **Pros:** True zero-downtime for any change, including type
  changes; the cutover happens at the routing layer.
- **Cons:** Two DB instances for every release; replication +
  cutover plumbing; large operational surface for a portfolio-grade
  demo.
- **Rejected because:** disproportionate cost for our scale. The
  expand→contract pattern handles 95% of changes; the remaining 5%
  (class C) are rare enough to deserve a deliberate maintenance
  window per change if they ever become necessary.

### Option C — A schema-migration tool with expand/contract built in (e.g. pgroll)
- **Pros:** Less hand-rolling; tooling enforces the pattern.
- **Cons:** Adds a deploy-time dependency; pgroll is relatively
  young (as of 2026-05); our Alembic-on-hand-written-revisions
  posture from CLAUDE.md is intentional ("never autogenerate").
- **Rejected for now:** Re-evaluate after a year of production
  ops. If the pattern friction is real, pgroll or similar lands as
  a follow-up ADR.

## Trade-off summary

| Dimension | Expand→contract (this) | Maintenance window | Blue/green |
|---|---|---|---|
| Zero-downtime | Yes (any class A/B) | No | Yes |
| Class-C handling | Forbidden; redesign | OK | OK |
| PR cost | 2 PRs per rename | 1 PR | 1 PR + ops cutover |
| Ops cost | Low | Low | High |
| Recruiter signal | Standard pattern, documented | Weak | Strong but expensive |

## Notes on the design docs

The Database Design doc says nothing about migration class
discipline. This ADR adds it; the implementation phase ports the
classification script to `tests/migrations/classify.py` and the
runbook entry to `docs/operations/runbooks/migrations.md`.

`Enterprise_RAG_Deployment.md` § "Database migrations" is the
existing surface for ops procedure — append a "Migration class
matrix" section there when the implementation lands.

## References

- [ADR-0012](0012-helm-argocd-deployment.md) — Helm + ArgoCD GitOps
  model, the constraint this ADR reconciles with
- [ADR-0032](0032-right-to-be-forgotten.md) — introduces
  `user_identity_map`, a class-B migration that's the first real
  exerciser of the pattern
- [Martin Fowler — Parallel Change](https://martinfowler.com/bliki/ParallelChange.html)
  — the canonical write-up of expand→contract
- [Postgres docs — ALTER TABLE locking](https://www.postgresql.org/docs/16/sql-altertable.html)
  — the source of truth for which `ALTER` commands take which lock
- CLAUDE.md / AGENTS.md — "every schema change is a hand-written
  Alembic revision, never `--autogenerate`"
