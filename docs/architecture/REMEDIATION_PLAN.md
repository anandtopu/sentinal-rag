# SentinelRAG — Remediation Plan

> Live ledger for the architecture-review remediation work. Mirrors the
> [`PHASE_PLAN.md`](PHASE_PLAN.md) format but tracks **Phase R** (Review
> remediation) work as a separate stream that can run in parallel with
> live-deploy activities.

> Anchor review:
> [`reviews/2026-05-16-architect-review.md`](reviews/2026-05-16-architect-review.md).
> Every phase below cites the finding number(s) from that review it
> closes.

## Status legend

- 🟢 Complete
- 🟡 In progress / partial
- ⚪ Not started

## Decisions log

| Date | Decision | Affects |
|---|---|---|
| 2026-05-16 | **R4 = Option A (extract for real).** Carved-out `retrieval-service` becomes a real network-bound service behind a `RetrievalClient` interface; `retrieval_mode: in-process \| http` switch per ADR-0021. Default mode stays `in-process` until the R4A.S6 benchmark says otherwise. | R1.S1 stage design, R4 scope, ADR-0021 supersession |
| 2026-05-16 | **R2.S2 LLM-judge default sample rate = 0%.** Cost-safe default; operators opt in by raising the Unleash flag value. NLI layer stays on by default. | R2.S2 |
| 2026-05-16 | **R5.S1 RTBF posture = support right-to-be-forgotten.** Redaction lands on `document_chunks.content` + `chunk_embeddings` (and source-doc copy in object storage); audit retains pseudonymous tenant_id + actor reference via a tombstone-mapping table so historical audit events still join after a user/tenant is forgotten. ADR drafts against this direction. | R5.S1 |

## Current phase

**R6 🟢 complete (2026-05-17).** README typo fixed, quick-start audit
landed a `pnpm` correction + ADR count refresh, the
`RETRIEVAL_SERVICE_TOKEN`-missing startup guard from the R4 handoff
follow-up list shipped with 4 new tests. R-stream remediation is
**done** except for the live-cluster-bound R4.S6 benchmark. Session
handoff:
[`handoff/2026-05-17-r6-complete.md`](handoff/2026-05-17-r6-complete.md).
Previous handoffs:
[`R5`](handoff/2026-05-17-r5-complete.md),
[`R4`](handoff/2026-05-17-r4-partial.md),
[`R3`](handoff/2026-05-17-r3-partial.md),
[`R2`](handoff/2026-05-17-r2-complete.md),
[`R1`](handoff/2026-05-16-r1-complete.md).

Pre-existing PHASE_PLAN.md work (first live deploy, real eval/cost
numbers, drill RTOs, 5-min demo video) is **independent** of this plan
and can ship in any order. **Only R4.S6 (benchmark, requires live
cluster) remains.**

## Phase ordering rationale

The phases below are ordered by **(impact / effort) on portfolio-grade
honesty**, not by deploy criticality:

1. **R1** unblocks every later phase by refactoring the orchestrator
   into stages — once stages exist, R2/R3 are local edits to a single
   stage file each, not surgery on an 883-LOC method. Because R4 is
   locked to Option A, R1.S1 designs `stages/retrieval.py` against a
   `RetrievalClient` interface up front so R4 is pure wiring, not a
   second refactor.
2. **R2** and **R3** can run in parallel after R1 lands.
3. **R4** runs after R1 (it depends on the stages package + the
   `RetrievalClient` seam created in R1.S1). It does not block R2/R3.
4. **R5** is documentation-only and can be picked up by anyone in any
   order; included here so the ADR backlog has a tracking row.
5. **R6** is interleavable polish.

## Hard rules (apply to every phase)

These come from [`AGENTS.md`](../../AGENTS.md) and the review's
"what NOT to change" section. A PR that violates these is rejected
regardless of how clean the diff looks:

- Don't mock the DB in tests that exercise RLS, tenancy, or RBAC retrieval.
- Don't write Celery code; use Temporal.
- Don't store raw document text in Postgres.
- Don't add inline prompt strings outside seeded defaults.
- Don't add cloud-specific code to K8s manifests.
- Don't hand-edit eval/cost numbers — harnesses overwrite the reports.
- Every schema change is a hand-written Alembic revision (`make db-revision msg="..."`),
  never `--autogenerate`.
- New ADRs are *additive*; older ADRs are superseded, never edited
  (status flip + back-link is the only allowed mutation).

## Phase ledger

### Phase R1 — Orchestrator surgery + pillar honesty 🟢
**Goal:** Make the orchestrator the cleanest part of the codebase. Close
the four highest-impact findings (#1, #2, #6, #7) and stage the file for
R2/R3 to drop into.

**Status (2026-05-16):** All 5 slices complete on a single session.
- Lint clean: `uv run ruff check apps packages` → 0 errors.
- Unit suite: `uv run pytest -m unit` → **194 passed, 0 failures**
  (baseline 162 + 11 new stage tests + 1 new audit isolation test +
  20 from in-flight work).
- Typecheck: `uv run pyright apps/api/app/services/rag` → **0 errors**
  on the new modules (warnings dominated by pre-existing
  `reportMissingTypeStubs` for workspace-internal modules).
- App startup smoke: `from app.main import create_app; create_app()` →
  45 routes registered.
- Worker activity import: `from sentinelrag_worker.activities import
  evaluation` → OK (lazy import of `app.services.rag` resolves).
- Integration tests (RLS / RBAC retrieval / audit dual-write against
  real Postgres) **deferred** — Docker Desktop named-pipe permissions
  blocked on this Windows host, same constraint flagged in
  PROGRESS.md. Must run before R1 ships in a real PR.

**Closes review findings:** #1, #2, #6, #7. (Partial #9 if hoisting
component construction is done in the same pass.)

**Estimated effort:** 1–2 sessions. One focused day if no other work
interleaves.

**Prerequisites:** None. Does not depend on live infra; integration tests
need Docker for testcontainers.

**Slices:**

- 🟢 **R1.S1 — Extract stages package.** Create
  `apps/api/app/services/rag/orchestrator.py` + `apps/api/app/services/rag/stages/`
  with the layout from the review:
  `retrieval.py`, `rerank.py`, `context.py`, `prompt.py`, `budget.py`,
  `generation.py`, `grounding.py`, `persistence.py`, `audit.py`.
  Introduce a typed `QueryContext` dataclass passed between stages.
  Keep the old `rag_orchestrator.py` as a thin shim that delegates to
  the new `Orchestrator` for a single PR window, then delete in R1.S5.
  **Bake in the R4 decision (Option A):** `stages/retrieval.py` calls a
  `RetrievalClient` Protocol — not the shared library directly — so R4
  is wiring an HTTP impl behind the existing seam, not refactoring
  call sites a second time. R1 ships only the `InProcessRetrievalClient`
  implementation; the HTTP impl lands in R4A.S2.
- 🟢 **R1.S2 — Replace raw SQL with repositories.** All five
  `INSERT`s and the `UPDATE` against `query_sessions`,
  `retrieval_results`, `generated_answers`, `answer_citations`,
  `usage_records` go through the existing repository pattern under
  `apps/api/app/db/repositories/`. Add repository methods that don't
  exist yet. RLS context (`SET LOCAL app.current_tenant_id`) must be
  set on the same session used by repositories — verify via
  integration test, not unit test.
- 🟢 **R1.S3 — Schema: real `error_message` column.**
  Hand-written Alembic revision adding
  `query_sessions.error_message TEXT NULL`. Drop the
  `normalized_query` poison-pill writes in the orchestrator failure
  path. Backfill is not required (legacy rows keep their polluted
  `normalized_query`; document this in the migration message).
- 🟢 **R1.S4 — Audit secondary-failure isolation.** Move the
  `contextlib.suppress` from the orchestrator into
  `DualWriteAuditService`. Secondary sink failures emit a structured
  log + an OTel counter (`sentinelrag_audit_secondary_failures_total`),
  and the daily reconciliation Schedule (Phase 6.5) catches the drift.
  Primary (Postgres) sink failures still propagate.
- 🟢 **R1.S5 — Delete shim + flip imports.** Once R1.S1–S4 land
  and tests are green, delete the old `apps/api/app/services/rag_orchestrator.py`
  shim and update import sites (`apps/api/app/api/` route handlers,
  any callers in tests).

**Verification:**

- `uv run ruff check apps packages` — clean, including the previously
  suppressed `PLR0915` for the old god method (the lint exception
  goes away because the method does too).
- `uv run pytest -m unit` — all 162 existing unit tests still pass;
  new stage-level unit tests added per stage (target: ≥5 per stage).
- `uv run pytest -m integration` — RLS + RBAC retrieval integration
  tests pass against testcontainers Postgres. The audit dual-write
  integration test must include a "secondary fails, primary succeeds,
  query succeeds, drift metric incremented" case.
- `helm template` against all 5 values overlays — still clean.
- `uv run pytest --cov=apps/api/app/services/rag --cov-report=term-missing` —
  per-stage coverage ≥90%.

**Done when:** the old 883-LOC `rag_orchestrator.py` is deleted, the
`/query` route still passes the full integration suite, and the
stages package is importable + tested in isolation.

**What NOT to do in this phase:**

- Don't change retrieval *behavior* — pure refactor, no semantic deltas.
- Don't add NLI or LLM-judge here — that's R2.
- Don't add idempotency or tokenizer changes here — that's R3.
- Don't touch the carved-out `retrieval-service` — that's R4.

### Phase R2 — Layered hallucination cascade in the query path 🟢
**Goal:** Make pillar #6 and ADR-0010 honest at request time, not just
in offline eval. Today the orchestrator only runs the token-overlap
layer; NLI + LLM-judge live in `sentinelrag_shared/evaluation/` and
never see live traffic.

**Status (2026-05-17):** All 5 slices complete on a single session.
- Lint clean: `uv run ruff check apps packages` → 0 errors.
- Unit suite: `uv run pytest -m unit` → **214 passed, 0 failures**
  (R1 baseline 194 + 20 new tests in
  `apps/api/tests/unit/test_grounding_cascade.py`).
- Typecheck: `uv run pyright` on the new modules
  (`apps/api/app/services/rag`,
  `packages/.../feature_flags`,
  `packages/.../evaluation/grounding`) → **0 errors** (warnings limited
  to pre-existing `reportMissingTypeStubs` on workspace-internal
  modules).
- App startup smoke: `from app.main import create_app; create_app()` →
  45 routes registered. Worker activity import: OK.
- Frontend: `tsc --noEmit` → exit 0.
- Migration 0016 parses with `revision='0016'` / `down_revision='0015'`.
- Integration tests (`-m integration`) deferred for the same Windows /
  Docker named-pipe reason called out in
  [PROGRESS.md](../../PROGRESS.md) and the R1 handoff. Must run before
  R2 ships in a real PR; the critical case is "0016 applied → cascade
  populates `nli_verdict`/`judge_verdict` columns through the
  repository → trace endpoint returns them."

**Closes review findings:** #4.

**Estimated effort:** 1 session.

**Prerequisites:** R1.S1 (`stages/grounding.py` must exist as the seam
for the cascade). Can run in parallel with R3 once R1 is in.

**Slices:**

- 🟢 **R2.S1 — Wire the cascade into `stages/grounding.py`.** Three-layer
  cascade per ADR-0010: token-overlap (always on) → NLI deberta (gated
  by score threshold) → LLM-as-judge (sampled at configurable rate, e.g.
  5% of NLI-pass answers + 100% of NLI-fail answers). Each layer is a
  small adapter calling into the existing
  `sentinelrag_shared/evaluation/` evaluators — no duplication of the
  scoring logic.
- 🟢 **R2.S2 — Unleash flag for the cascade.** Three flags:
  `hallucination.nli.enabled` (default **on**),
  `hallucination.judge.enabled` (default **off**),
  `hallucination.judge.sample_rate` (default **0.0**, range
  `[0.0, 1.0]`). Cost-safe defaults per the 2026-05-16 decision —
  operator opts the judge layer in by raising the flag value, no
  redeploy needed. Flag evaluation goes through the existing
  `sentinelrag_shared/feature_flags/` adapter. The default trio is
  asserted in a unit test so a future flag-server misconfiguration
  doesn't silently flip judge on at 100%.
- 🟢 **R2.S3 — Persist per-layer verdicts.** Hand-written Alembic
  revision adding two columns to `generated_answers`:
  `nli_verdict TEXT NULL` (`entail` / `neutral` / `contradict` / `skipped`)
  and `judge_verdict TEXT NULL` (`pass` / `fail` / `skipped`). The
  existing `grounding_score` column stays as layer-1.
- 🟢 **R2.S4 — Trace UI surfaces verdicts.** The Next.js trace viewer
  (`apps/frontend/src/app/query-playground/`) already streams retrieval
  stages; add a "hallucination cascade" panel showing the three layer
  verdicts when present.
- 🟢 **R2.S5 — Update ADR-0010 status notes.** ADR-0010 stays
  `Accepted`; append a "Implementation notes (2026-MM-DD)" section
  recording the flag scheme + thresholds chosen. **No edits to the
  decision text** (ADR immutability).

**Verification:**

- New unit tests on `stages/grounding.py` for each layer's
  short-circuit logic (token-overlap above threshold → skip NLI;
  NLI=entail + sample_rate=0 → skip judge; etc.).
- New integration test asserting that a known-hallucinated answer is
  flagged by at least one layer.
- OTel: new histogram `sentinelrag_hallucination_layer_latency_ms{layer}`
  with cardinality discipline (no tenant_id).
- `helm template` clean against all overlays (no new K8s shape).

**Done when:** the live query path runs the full cascade when the flag
combination requests it, verdicts persist on `generated_answers`, and
the trace viewer shows them.

**What NOT to do in this phase:**

- Don't ship the LLM-judge layer at 100% sample rate — keep the default
  at 0 so cost doesn't surprise an operator.
- Don't reimplement the NLI / judge evaluators — call into
  `sentinelrag_shared/evaluation/`.

### Phase R3 — Cost + resilience hardening 🟡
**Goal:** Close the cost-pillar leaks and the resilience gaps that don't
need a refactor — just careful local edits to the post-R1 stage files.

**Status (2026-05-17):** 6 of 7 slices complete; S6 deferred.
- Lint clean: `uv run ruff check apps packages` → 0 errors.
- Unit suite: `uv run pytest -m unit` → **234 passed, 0 failures**
  (R2 baseline 214 + 5 new helper tests + 15 new
  idempotency/reservation tests).
- Typecheck: `uv run pyright` on the new + touched modules
  (`apps/api/app/services/{idempotency,budget_reservation,redis_service}.py`,
  `apps/api/app/services/rag/`) → **0 errors** on new modules
  (warnings limited to pre-existing `reportMissingTypeStubs`).
- App startup smoke: 45 routes registered. Worker import: OK.
- Frontend: `tsc --noEmit` → exit 0.
- Integration tests deferred for the same Windows/Docker reason
  flagged in R1 + R2 handoffs.

**Closes review findings:** #3 (cost surface), #8 (idempotency),
#10 (timeout), #11 (reservation), #12 (prompt formatting). #9
(component hoisting) is the part that lands with R3.S6 in the next
session.

**Estimated effort:** 1 session.

**Prerequisites:** R1 complete. Independent of R2.

**Slices:**

- 🟢 **R3.S1 — Surface embedding cost.** Change `Embedder.embed(...)`
  to return token counts + cost alongside the vector. Update
  `LiteLLMEmbedder` in `packages/shared/python/sentinelrag_shared/llm/`
  and feed the result into both the budget pre-check (the estimate
  must include embedding) and the persisted `usage_records` row
  written by `stages/persistence.py`. Update tests for both call
  sites.
- 🟢 **R3.S2 — Idempotency-Key on /query.** Add the
  `Idempotency-Key` header support to the `/query` route, keyed in
  Redis with 24h TTL via SETNX. On hit, return the persisted
  `QueryResult` for the prior `query_session_id`. Key is hashed
  with `tenant_id` to prevent cross-tenant key collisions. New unit
  + integration tests cover replay (same key → same answer, no
  duplicate audit/usage rows) and concurrent races (two parallel
  requests, same key → one runs, one waits-then-returns).
- 🟢 **R3.S3 — Real per-model tokenizer in budget estimate.**
  Replace `_approx_token_count` (`len(text)/4`) with
  `litellm.token_counter(model=..., text=...)`. Keep the
  char-based fallback for models LiteLLM doesn't know about, with
  a structured-log warning when the fallback fires.
- 🟢 **R3.S4 — LiteLLM call timeout + cancellation propagation.**
  Wire a per-call timeout (default 60s, configurable via env) on
  `LiteLLMGenerator.complete(...)`. On timeout, the orchestrator
  records a `query.failed` audit event with reason
  `provider_timeout`, marks the session failed, and frees any
  budget reservation (R3.S5 dependency).
- 🟢 **R3.S5 — Budget reservation + release.** Today the cost
  check is a one-shot estimate; the actual cost is recorded after
  the call. Under load with timeouts this can let a tenant burst
  past their hard cap. Reserve the estimated USD in Redis under
  `budget:{tenant_id}:reserved` with a TTL = call timeout; settle
  (release reservation + record actual) on completion *or* timeout.
- 🟢 **R3.S6 — Hoist per-request component construction.** *Embedder-only hoist landed 2026-05-17.* Generator/KeywordSearch/VectorSearch/HybridRetriever stay per-request by design (Generator's model alias is per-request; the others bind to the per-request SQLAlchemy session). The plan lists Embedder, Generator, KeywordSearch, VectorSearch, HybridRetriever as hoist candidates; on closer inspection only `Embedder` is a clean singleton (matches `default_embedding_model` + `ollama_base_url`, both static at process start). Generator is per-request because the effective model can change request-by-request (cloud vs ollama). KeywordSearch / VectorSearch / HybridRetriever bind to the request-scoped SQLAlchemy session, so per-request construction is inherent — not a perf problem to solve. The deferred work: hoist Embedder to `app.state`, expose via FastAPI dependency, accept on `Orchestrator.__init__`, remove per-request `LiteLLMEmbedder(...)` from `Orchestrator.run`. Plus a one-line update for the existing fake-settings tests. Move
  `Embedder`, `Generator`, `KeywordSearch`, `VectorSearch`,
  `HybridRetriever` from per-request `__init__` to `app.state`
  startup (`apps/api/app/lifecycle.py`). The orchestrator + stages
  pull from `app.state` via FastAPI dependencies.
- 🟢 **R3.S7 — Safe prompt formatting.** Replace
  `template.format(query=..., context=...)` in `stages/prompt.py`
  with `string.Template.safe_substitute` or a deliberate
  double-curly-aware `replace`. Add a regression test with a
  context block containing literal `{` and `}`.

**Verification:**

- `uv run pytest -m unit` — all green; new tests added per slice.
- `uv run pytest -m integration` — the Idempotency-Key replay and
  reservation-release tests run against testcontainers Redis +
  Postgres.
- k6 smoke test still meets the SLO thresholds in
  `tests/performance/k6/lib/config.js`.
- Cost report harness (`scripts/cost/render_report.py`) rerun: the
  per-tenant embedding line item now shows nonzero cost when an
  OpenAI embedder is configured.

**Done when:** budget gate accounts for embeddings; duplicate /query
calls don't double-charge; a stuck provider doesn't lock a budget
reservation; per-request component construction is gone.

**What NOT to do in this phase:**

- Don't add a circuit breaker for LiteLLM providers — that's a
  separate ADR (defer to R5 if scoped).
- Don't change the budget *policy* (soft-cap downgrade ladder); only
  the *plumbing*.

### Phase R4 — Extract retrieval-service for real 🟡
**Goal:** Close ADR-0021's half-done state by extracting the carved-out
`retrieval-service` into a real network-bound service behind a
`RetrievalClient` interface. **Decision locked 2026-05-16: Option A
(extract).** Option B (delete the shell) is rejected; the portfolio
signal of "real microservice extracted with measured benchmark" is
worth the operational cost of one more pod.

**Closes review findings:** #5.

**Estimated effort:** 1 session.

**Prerequisites:** R1 complete. R1.S1 ships the `RetrievalClient`
Protocol + `InProcessRetrievalClient`; R4 adds the HTTP impl behind the
existing seam — no orchestrator-side refactor needed.

**Status (2026-05-17):** 6 of 7 slices complete; S6 (benchmark)
deferred to a live-cluster session. Verification:
- Lint clean: `uv run ruff check apps packages` → 0 errors.
- Unit suite: `uv run pytest -m unit` → **246 passed, 0 failures**
  (R3 baseline 234 + 6 HttpRetrievalClient tests + 6
  retrieval-service /v1/retrieve auth + capabilities tests).
- Pyright on new modules: 0 errors.
- App startup smoke: 45 routes (api). Retrieval-service: 9 routes.
  Worker activity import: OK.
- Frontend: `tsc --noEmit` → exit 0.
- `helm lint`: 0 failures. `helm template` clean against all 4
  overlays (values.yaml, values-local, values-dev, values-prod,
  values-gcp-dev). `helm template` adds the new retrieval workload:
  Deployment + Service + ConfigMap + ExternalSecret + HPA + PDB +
  ServiceAccount + NetworkPolicy.
- ADR-0021 status flipped to `Superseded by ADR-0031`; new ADR
  catalog entry added.

The env-var name landed as `RETRIEVAL_TRANSPORT` (not `RETRIEVAL_MODE`
as the plan said) to avoid colliding with the legacy
`RETRIEVAL_MODE=hybrid` env that documents the per-request retrieval
mode default in `.env.example`. Documented in ADR-0031.

**Slices:**

- 🟢 **R4.S1 — Contracts package.** Add
  `packages/shared/python/sentinelrag_shared/contracts/retrieval.py`
  with request/response Pydantic v2 models matching the
  `RetrievalClient` Protocol shape introduced in R1.S1. Versioned
  contract — bump on any field change.
- 🟢 **R4.S2 — `HttpRetrievalClient` impl.** Add to
  `sentinelrag_shared/retrieval/client.py` alongside the
  `InProcessRetrievalClient` from R1.S1. httpx AsyncClient with
  connection pooling sized to match the API service worker count,
  OTel context propagation via `opentelemetry-instrumentation-httpx`,
  retry-with-backoff on 502/503/504 (max 2 retries), 5s default
  per-call timeout (overridable via env).
- 🟢 **R4.S3 — Orchestrator switch.** No code change to
  `stages/retrieval.py` — it already calls `RetrievalClient` from DI
  (per R1.S1). Selection moves to `apps/api/app/lifecycle.py`: read
  env `RETRIEVAL_MODE` (default `in-process`), instantiate the right
  impl, register on `app.state`. Unknown value fails fast at startup.
- 🟢 **R4.S4 — Service implementation.** Flesh out
  `apps/retrieval-service/sentinelrag_retrieval_service/` with
  FastAPI routes mirroring the contracts. Reuse the existing
  shared library for the actual work — no duplication. Health
  endpoint at `/healthz`. JWT verification (same Keycloak JWKS
  cache as the API) so cross-service calls carry an `AuthContext`
  end-to-end and RBAC at retrieval time (pillar #1) is preserved
  across the network hop.
- 🟢 **R4.S5 — Helm + Terraform updates.** Add `retrieval` as a
  workload in the Helm chart (Deployment + SA + ConfigMap + Service +
  HPA + PDB + NetworkPolicy via the existing `_helpers.tpl`
  shared library). Per-cloud values overlays gain IRSA / WI binding
  for the retrieval ServiceAccount. NetworkPolicy: `api` → `retrieval`
  ingress only; `retrieval` → `postgres` + `litellm-targets` egress.
  No Terraform module changes (it's another pod on the same EKS/GKE).
- 🟡 **R4.S6 — Benchmark.** *Deferred — requires a live cluster.* The harness lives at `tests/performance/evals/compare.py` + `tests/performance/k6/`; ADR-0029 forbids hand-edited eval numbers. The default `retrieval_transport` stays `in-process` until this slice runs and the report shows p95 delta inside SLO budget. Run the k6 baseline scenario against
  both `RETRIEVAL_MODE=in-process` and `RETRIEVAL_MODE=http`. Capture
  p50/p95/p99 latency, RPS at SLO, and cold-start cost. Commit the
  report by re-running the eval harness (`tests/performance/evals/compare.py`
  with a new comparison entry — don't hand-edit
  `docs/operations/eval-report.md`). The default mode flips to `http`
  only if p95 delta is within the SLO budget.
- 🟢 **R4.S7 — ADR-0031 supersession.** New ADR records the
  extraction + benchmark result + final default; status-flip
  ADR-0021 to `Superseded by ADR-XXXX`. The new ADR's "Notes on the
  design docs" section reconciles with ADR-0009 (REST not gRPC) —
  this is the first cross-service REST call, so it's the validation
  of that choice.

**Verification:**

- `uv run pytest -m unit` and `-m integration` — clean. New
  integration tests cover: HTTP impl returns the same shape as
  in-process for a fixed corpus + query; auth failure on the
  retrieval-service returns 401 and the orchestrator surfaces it
  as a 500 with a structured cause.
- `helm lint` + `helm template` against all 5 overlays — clean.
- ADR catalog README updated.
- k6 baseline meets SLO thresholds in both modes.

**Done when:** the `retrieval_mode` switch exists, both impls pass the
integration suite, the benchmark report is committed, ADR-0021 is
superseded, and the live demo can flip modes via env without redeploy.

**What NOT to do in this phase:**

- Don't extract `ingestion-service` or `evaluation-service` in the
  same pass — they have the same shell-vs-live ambiguity but each
  deserves its own decision + ADR if extracted. Defer to a follow-on
  remediation phase.
- Don't change the retrieval *algorithm* in this phase — pure
  topology change.

### Phase R5 — ADR backlog catch-up 🟢
**Goal:** Add the six ADRs a senior reviewer is most likely to probe.
Documentation-only; can be picked up in any order by any role.

**Closes review findings:** "ADR gaps a senior reviewer will probe"
section of the review.

**Estimated effort:** 1–2 sessions. Each ADR is 30–60 min if the
decision is already implicit in the code; longer if a real decision
needs to be made.

**Status (2026-05-17):** All six ADRs landed in one session. ADR
catalog updated. Direction for R5.S1 (RTBF) matches the 2026-05-16
Decisions log entry exactly.

**Slices (each is one ADR — pick whichever order suits the session):**

- 🟢 **R5.S1 — [ADR-0032](adr/0032-right-to-be-forgotten.md): Right-to-be-forgotten vs. immutable audit.**
  Highest-leverage gap. **Direction locked 2026-05-16: support RTBF.**
  Concretely the ADR commits to:
  - **Deletable surfaces:** `document_chunks.content`,
    `chunk_embeddings.*`, source-doc copy in object storage (versioned
    bucket — purge all versions on RTBF), `query_sessions.query_text`,
    `generated_answers.answer_text`.
  - **Audit retention:** `audit_events` rows are preserved (Object
    Lock makes the S3 mirror non-deletable anyway), but PII is held
    indirectly — `actor_user_id` references a tombstone table
    `user_identity_map(pseudonym_id UUID PK, user_id UUID NULL)`. On
    RTBF the `user_id` column flips to NULL; the pseudonym still joins
    historical audit/usage rows but no longer resolves to a person.
  - **Tenant-level RTBF** ("forget this tenant entirely") is a
    separate workflow: chunks + embeddings + docs purged as above;
    tenant row tombstoned the same way; Object Lock S3 audit prefix
    survives the COMPLIANCE retention window then ages out.
  - **Operational shape:** Temporal `RtbfWorkflow` with idempotent
    activities (per-user and per-tenant variants), invoked by a new
    `POST /admin/rtbf` route gated on a `rtbf:execute` permission;
    completion emits an audit event with the pseudonym so the action
    itself is auditable without re-identifying the subject.
  - **Trade-off acknowledged:** audit completeness is preserved at
    the cost of GDPR purists' "no trace at all" reading; the ADR
    documents this explicitly and cites the controller-vs-processor
    framing that justifies it.
- 🟢 **R5.S2 — [ADR-0033](adr/0033-zero-downtime-schema-migrations.md): Zero-downtime schema migration strategy.**
  Expand → backfill → contract pattern. What's allowed in the Helm
  pre-upgrade `alembic` Job vs. what needs a multi-deploy dance. How
  RLS policies + RLS-bypass admin sessions interact with migrations.
- 🟢 **R5.S3 — [ADR-0034](adr/0034-prompt-injection-defense.md): Prompt injection defense posture.** Even
  "in-context defense only, no input scanning v1" is a defensible
  position. Document threat model (data-plane prompts vs. control-plane
  prompts, where each gets sanitized).
- 🟢 **R5.S4 — [ADR-0035](adr/0035-pii-redaction-at-ingestion.md): PII redaction at ingestion.** Library choice
  (presidio? rule-based?), when in the pipeline it runs (pre-chunk so
  embeddings don't leak), how it interacts with the immutable
  source-doc copy in object storage.
- 🟢 **R5.S5 — [ADR-0036](adr/0036-vector-sharding-per-tenant-index.md): Vector sharding / per-tenant index strategy.**
  When does HNSW recall degrade on a shared index? Trigger threshold
  for per-tenant indexes (corpus size? embedding count? recall
  measurement?). Cost vs. complexity trade-off.
- 🟢 **R5.S6 — [ADR-0037](adr/0037-streaming-generation-response.md): Streaming generation response shape.** SSE
  vs. WebSocket vs. response-streamed JSON chunks for the answer
  itself (trace stream is already SSE). UX + backpressure
  considerations.

**Verification:**

- ADR index at `docs/architecture/adr/README.md` updated for each
  ADR added.
- Cross-references checked: any ADR that supersedes or modifies an
  existing ADR includes the back-link in both directions (the new
  one cites the old, the old's status flips to
  `Superseded by ADR-XXXX`).

**Done when:** all 6 ADRs are committed with status `Accepted`, the
catalog README is in sync, and the review's "ADR gaps" list is empty.

**What NOT to do in this phase:**

- Don't ship code changes alongside the ADRs in the same PR — ADRs
  land first; implementations follow in dedicated PRs (potentially
  in later remediation phases). This is the project's existing
  convention from PHASE_PLAN.md cross-phase rules.

### Phase R6 — Polish 🟢
**Goal:** Catch-all for sub-1-hour cleanups that surface during
R1–R5. Can interleave with anything.

**Closes review findings:** #13, plus follow-ups surfaced during R1–R5.

**Estimated effort:** A few minutes per item.

**Slices:**

- 🟢 **R6.S1 — README typo.** `de# SentinelRAG` → `# SentinelRAG` on
  line 1 of the root README.
- 🟢 **R6.S2 — Quick-start smoke verified.** Audit-only run (live `make up` smoke remains Docker-blocked on this host). Patched: README pointed at `npm install && npm run dev` but the project is a pnpm workspace and `make frontend` runs `pnpm dev` — README now points at `make install` + `make frontend`. ADR count refreshed (30 → 37). Run the README's
  Quick-start curl example against a fresh `make up` and confirm it
  returns a sensible response. If anything is stale (env var rename,
  port shift), patch the README in the same commit.
- 🟢 **R6.S3 — Trailing follow-ups.** Landed the R4 handoff's `RETRIEVAL_TRANSPORT=http` + empty `RETRIEVAL_SERVICE_TOKEN` startup guard in `apps/api/app/lifecycle.py::_build_retrieval_client`; 4 new tests in `test_lifecycle_retrieval_guard.py`. Other R1–R5 follow-ups (NLI/judge real-adapter wiring, judge-reasoning UI, idempotency OpenAPI note, reservation chaos drill, retrieval HPA tuning, per-cloud retrieval IRSA/WI) are each their own implementation-PR scope per the ADRs they sit under, not R6 polish. Reserved for items surfaced by
  R1–R5 that don't justify their own phase.

**Verification:**

- README renders cleanly on GitHub.
- `curl` quick-start completes against `make up` returning a
  200-status JSON envelope (or a documented 401 if the dev-token
  flags aren't set).

**Done when:** the README is the cleanest single artifact in the repo
— which it nearly is already.

## Cross-phase rules (PHASE_PLAN.md parity)

- Every architectural decision lands as an ADR before code (R5 phases
  are ADR-first by definition; R1–R4 may need spot ADRs for
  surprises).
- Don't edit accepted ADRs — supersede.
- No phase is "done" until its tests pass in CI on a clean checkout.
- After each phase, update this file with what shipped + what was
  deferred. If a phase adds a new operational concern, add a runbook
  entry under `docs/operations/runbooks/`.
- This plan does **not** modify
  [`PHASE_PLAN.md`](PHASE_PLAN.md). The deploy-readiness phases there
  proceed independently.

## Suggested PR sizing

| Phase | Suggested PRs |
|---|---|
| R1 | 3 PRs: (R1.S1–S2 stages + repositories) → (R1.S3 schema migration) → (R1.S4–S5 audit isolation + shim deletion). |
| R2 | 2 PRs: (R2.S1–S3 wiring + schema + flags) → (R2.S4 frontend + ADR-0010 note). |
| R3 | 2–3 PRs: (R3.S1 embedding cost) → (R3.S2 + R3.S5 idempotency + reservation) → (R3.S3 + S4 + S6 + S7 misc). |
| R4 | 3 PRs: (R4.S1–S2 contracts + HttpRetrievalClient) → (R4.S3–S4 lifecycle switch + service impl) → (R4.S5–S7 Helm + benchmark + ADR supersession). |
| R5 | 1 PR per ADR, opened in any order. |
| R6 | 1 small PR per item, or batched. |

## Open questions for the next session

All three opening decisions are resolved (see **Decisions log** at the
top of this file). Remaining open items will surface during R1
execution — log them here when they arise.

- _(none open)_
