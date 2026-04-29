# ADR-0029: Portfolio polish — Mermaid C4 diagrams, harness-with-placeholder reports, README as the front door

- **Status:** Accepted
- **Date:** 2026-04-29
- **Tags:** documentation, portfolio, evaluation

## Context

Phase 9 ships the readable artifacts a senior engineer (or recruiter)
should be able to absorb in 30 minutes. The original Phase 9 plan in
`PHASE_PLAN.md` lists six deliverables:

1. Root README with architecture diagram, quick-start, live demo URL.
2. C4 diagrams in `docs/architecture/c4/`.
3. ADR index complete and current.
4. Cost report (1 month synthetic traffic).
5. Eval report: before/after hybrid retrieval, with-/without-rerank, prompt v2 vs v1.
6. 5-minute demo video.

Three of those (cost report, eval report, demo video) need real running
infrastructure to produce numbers worth committing. The rest are pure
documentation. This ADR pins the **shape** of the polish so the artifacts
are useful even before a deployed environment exists.

## Decision

### C4 diagrams as Mermaid, rendered natively by GitHub

`docs/architecture/c4/` ships five files: `L1-system-context.md`,
`L2-container.md`, `L3-component-rag-core.md`, `L4-deployment-aws.md`,
`L4-deployment-gcp.md`. Each uses the Mermaid `C4Context` / `C4Container`
/ `C4Component` / `C4Deployment` syntax. GitHub renders Mermaid in `.md`
files in PRs and the web UI — diagrams are part of the diff and can be
reviewed line by line.

Each diagram file ends with a "Related ADRs" section linking the
decisions visible at that level. So the diagrams are not just pictures —
they are the visual index into the ADR catalog.

### README as the 30-minute walkthrough

The root README is structured for a recruiter to skim, not a maintainer
to reference. Order:

1. One-line tagline + subtitle paragraph naming the load-bearing
   capabilities ("multi-tenant RBAC at retrieval time, hybrid retrieval,
   layered hallucination detection, per-tenant cost budgets, immutable
   audit").
2. Mermaid architecture diagram inline (so the reader sees shape before
   they read text).
3. Pointers to the four C4 diagrams.
4. "Where to read the rationale" — CLAUDE.md, ADR catalog, PHASE_PLAN,
   DR runbook, original PRD/design docs.
5. Stack table with each row linked to the ADR that pinned it.
6. Repository tour.
7. Quick start.
8. Build status + remaining work (honestly: Phase 7 Slice 3 cluster
   bootstrap is still pending; the demo video is ungenerated).
9. Things-not-to-do (the recurring footguns).
10. License.

The README does NOT try to be the complete documentation surface. It is
a launching pad with the diagram and the ADR pointers. Detailed docs
live where they belong — in `docs/architecture/`,
`docs/operations/runbooks/`, and the per-module READMEs.

### Cost + eval reports ship as harnesses with placeholder reports

We can't fabricate real-traffic eval numbers or cost numbers and call them
honest. Instead:

- **Eval comparison harness** at `tests/performance/evals/compare.py`
  produces a markdown report at `docs/operations/eval-report.md` from a
  before/after run against a deployed API. Three comparisons are wired:
  `hybrid-vs-vector`, `rerank-vs-no`, `prompt-v2-vs-v1`. A 3-case JSON
  fixture under `tests/performance/evals/fixtures/dataset.json` lets the
  harness self-check without a seeded eval dataset.

  The committed `eval-report.md` is a placeholder that describes the
  expected report shape and where the real numbers will land. It's
  overwritten on the first real run.

- **Cost report harness** is two scripts:
  `scripts/cost/synthetic_month.py` emits a 30-day, 4-tenant CSV that
  mirrors the `usage_records` shape;
  `scripts/cost/render_report.py` renders it to
  `docs/operations/cost-report.md`. The committed report is rendered
  from the synthetic CSV (seed=42) so the file shows real numbers
  rendered through the real pipeline. The synthetic CSV itself is
  gitignored — it's regenerable.

This pattern — **harness in the repo, placeholder report committed,
overwritten on first real run** — is honest about the state ("we have
the tools; we haven't run them against real data yet") and useful from
day one (the harness exists for the next operator to invoke).

### What we did NOT do

- **No PNG renders of the C4 diagrams.** Mermaid in GitHub renders
  natively; PNGs would need a build step + asset pipeline + a place to
  host them, and the rendered visual is no better.
- **No Structurizr DSL.** Source-of-truth Structurizr is more rigorous
  but requires a separate render step and a hosted Structurizr server
  (or static-site export). The cost outweighs the polish gain at our
  scope.
- **No demo video committed.** Recording a real 5-minute video requires
  the deployed dev environment that Phase 7 Slice 3 still owes. When
  the environment lands, recording is a one-day task; trying to
  pre-record against a dev-stack-only system would be misleading.
- **No fabricated eval numbers in the report.** A made-up eval table
  would be worse than a placeholder — it would actively mislead.
- **No interactive playground link.** `app.dev.sentinelrag.example.com`
  is a placeholder until the cluster bootstrap (Phase 7 Slice 3)
  ships. The README says so.

## Consequences

### Positive

- The repo is recruiter-readable today even though three of the six
  Phase 9 deliverables are "harness shipped, real-data run pending."
  The harnesses are themselves the demonstration of competence (eval
  harness reuses the existing `Evaluator` protocol; cost harness uses
  the same pricing snapshot the production `CostService` uses).
- C4 diagrams in Mermaid stay in sync with the ADRs because they live
  in the same directory and link to each other.
- Adding a new comparison (e.g. "ragas vs custom evaluators") is one
  config entry in `compare.py`, not a new doc.

### Negative

- The committed eval report is a placeholder; a recruiter who only
  reads `docs/operations/eval-report.md` without reading the
  methodology section will think we have nothing. Mitigated by the
  README explicitly marking the live-environment dependencies and by
  the report itself naming its placeholder status in the title.
- Mermaid C4 doesn't render outside GitHub (e.g. in plain `.md`
  preview tools, or printed PDFs). For a strictly portfolio repo
  this is acceptable; if we ever need print-ready exports, generating
  PNGs from the Mermaid sources is a one-script add.

### Neutral

- The synthetic-month CSV is gitignored. The committed cost report is
  always rendered fresh from synthetic data with seed=42 — same
  numbers each render. We document the seed in the report's
  Methodology section.

## Alternatives considered

### Option A — Static numbers in the eval + cost reports
- **Pros:** Recruiter sees "real" numbers without the placeholder
  caveat.
- **Cons:** They wouldn't be real. We'd be lying.
- **Rejected because:** integrity matters more than perceived
  completeness.

### Option B — Structurizr DSL for C4 with rendered PNGs in the repo
- **Pros:** Industry-standard tool; print-ready.
- **Cons:** Build step + render pipeline; PNG bloats the repo; PNG +
  source go out of sync.
- **Rejected because:** Mermaid in GitHub is good enough at this scale.

### Option C — One giant `ARCHITECTURE.md` instead of L1-L4 split
- **Pros:** Fewer files to navigate.
- **Cons:** Loses the C4 zoom-level discipline; readers can't pick the
  level they care about; ADR↔diagram linking gets cluttered.
- **Rejected because:** the C4 model exists for a reason.

## Trade-off summary

| Dimension | Mermaid + harness (this) | Structurizr + real numbers | Static numbers in markdown |
|---|---|---|---|
| Diagrams render | GitHub-native | requires render step | n/a |
| Cost report integrity | placeholder until real run | requires deployed env | risks fabricated numbers |
| Maintenance cost | low | medium | low |
| Recruiter signal | strong (tools shipped + honesty) | strongest (with real numbers) | weak (if numbers smell fake) |

## Notes on the design docs

`Enterprise_RAG_PRD.md` §13 lists portfolio deliverables. This ADR
implements those deliverables in a way that is honest about which ones
need a deployed environment.

## References

- C4 model: <https://c4model.com/>
- Mermaid C4 syntax: <https://mermaid.js.org/syntax/c4.html>
- ADR-0019 — evaluation framework (powers the eval harness)
- ADR-0022 — cost budgets (the pricing snapshot the cost report uses)
- ADR-0028 — DR runbook (the operational doc the README points to)
