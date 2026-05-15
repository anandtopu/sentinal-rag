# Feature testing guide

How to verify every documented SentinelRAG feature works after a code
change. This is the **canonical test matrix** — when AGENTS.md or a
README quick-start disagrees with this file, this file wins.

The guide is layered:

1. **Automated** — what runs in CI / pytest / vitest.
2. **Local manual smoke** — what you click + curl against `make up`
   to prove the feature end-to-end against the local stack.
3. **Deployed environment** — what to verify after `terraform apply`
   and the bootstrap stack are live.

Each feature carries a "fail signal" — what to look for if the
test should have caught a bug but didn't.

---

## How to run the automated suites

```bash
# Unit tests — fast, no infra, run on every PR.
uv run pytest -m unit
# Expect: 162 passed, 0 failures, 0 flakes.

# Integration tests — testcontainers, needs Docker Desktop.
uv run pytest -m integration

# Frontend unit tests.
cd apps/frontend && npm run test
# Expect: 5 passed (api client).

# Frontend e2e — Playwright; the API-dependent specs auto-skip when
# the backend isn't reachable. Defaults to :3107 to avoid dev-server
# collisions; set E2E_PORT or E2E_REUSE_SERVER=true when needed.
cd apps/frontend && npm run test:e2e
# Expect: 15 tests total. Frontend-only: 11 passed, 4 skipped.

# Lint + format + typecheck.
uv run ruff check apps packages scripts tests   # → All checks passed!
uv run ruff format --check
uv run pyright apps packages   # ~154 baseline errors documented; not blocking
```

Helm chart linting:
```bash
cd infra/helm/sentinelrag
for f in values.yaml values-dev.yaml values-gcp-dev.yaml values-prod.yaml values-local.yaml; do
  helm lint . -f $f
done
# All five must pass.
```

---

## Feature matrix

### F1. Multi-tenant isolation via Postgres RLS

**Architectural pillar #2** — every Postgres query carries
`SET LOCAL app.current_tenant_id`; RLS policies enforce isolation as
defense in depth.

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_jwt_verifier.py` — 5 JWT scenarios. |
| Integration | `uv run pytest -m integration apps/api/tests/integration/test_rls_isolation.py` — proves cross-tenant read/write returns 0 rows. |
| Manual | `make up && make seed`. Mint two demo tenants. From tenant A, `POST /query` against a collection in tenant B's namespace → expect 404 (collection not visible), not 403 (which would imply post-mask). |

**Fail signal:** if a unit test mocks `AsyncSession`, the RLS bug surface
is hidden. AGENTS.md forbids this — see ADR-0008 + Pillar #2.

---

### F2. RBAC at retrieval time, not post-mask

**Architectural pillar #1** — the hybrid retriever receives an
`AuthContext` and injects an authorized-collections CTE into BOTH the
BM25 and vector queries before candidates are fetched.

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_opensearch_keyword_search.py` — covers the same authorized-collections resolution path used by both backends. |
| Integration | `uv run pytest -m integration apps/api/tests/integration/test_retrieval_rbac.py` — issues `/query` as user A; checks zero rows from collections only user B has access to (when integration suite is up). |
| Manual | After `make seed`, demote the demo-admin user to read-only on collection X; issue `/query` with a question whose only matching chunk is in X → expect zero citations from X. |

**Fail signal:** seeing a citation from a collection the user can't
read. The fix is **never** "filter out the citation in the response
serializer" — it means the access filter didn't hit the SQL. See
`packages/shared/python/sentinelrag_shared/retrieval/access_filter.py`.

---

### F3. Hybrid retrieval (BM25 + vector + RRF + rerank)

**ADR-0003 / 0004 / 0006 / 0026.** The retrieval pipeline is BM25 →
vector → RRF merge → optional rerank.

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_chunkers.py apps/api/tests/unit/test_opensearch_keyword_search.py` |
| Manual | `POST /api/v1/query` with `retrieval.mode=hybrid` and `retrieval.top_k_rerank=8`. Hit the same query with `mode=vector` and `top_k_rerank=0`. Compare the trace via `GET /query/{id}/trace` — counts per stage (`bm25`, `vector`, `hybrid_merge`, `rerank`) should differ. |
| A/B report | `uv run python tests/performance/evals/compare.py --compare hybrid-vs-vector ...` — produces `docs/operations/eval-report.md` with the ContextRelevance + Faithfulness deltas. See `tests/performance/evals/README.md`. |

**Fail signal:** if `top_k_rerank=8` and the rerank stage isn't in the
trace, the lazy-loaded reranker isn't initializing — check
`enable_reranker=true` and the bge model download.

---

### F4. Versioned prompts as first-class artifacts

**Architectural pillar #4.** Generation persists `prompt_version_id` on
`generated_answers`. No inline prompt strings outside seeded defaults.

| Layer | What to run |
|---|---|
| Manual | `POST /api/v1/prompts` to create a template; `POST /api/v1/prompts/{id}/versions` for v1 and v2 (mark v2 as default). Run `/query`; inspect the response — the answer should be persisted with `prompt_version_id` matching v2. |
| A/B report | `uv run python tests/performance/evals/compare.py --compare prompt-v2-vs-v1 --before-prompt-id <v1-uuid> --after-prompt-id <v2-uuid> ...` |

**Fail signal:** `grep -r "You are a helpful assistant" apps/ packages/`
should ONLY hit seeded-defaults files (`scripts/seed/`). If it hits
`apps/api/app/services/`, that's a violation of pillar #4.

---

### F5. Per-tenant cost budgets (soft-cap downgrade, hard-cap deny)

**ADR-0022.** `CostService` runs after retrieval/rerank, before
generation. Soft cap rebinds the LiteLLM generator to a cheaper model;
hard cap raises `BudgetExceededError` (HTTP 402).

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_cost_service.py` — 11 tests covering estimate, allow / downgrade / deny boundaries, exception mapping. |
| Manual | After `make seed`, `INSERT INTO tenant_budgets (...)` with `soft_cap_usd=0.001` and `hard_cap_usd=0.005`; issue `/query` repeatedly with an expensive model. The 1st request should downgrade (response field `effective_model` ≠ requested `model`); a later request should fail with HTTP 402. |
| OTel | Inspect Grafana → `cost-tenant` dashboard. The `sentinelrag_budget_decisions_total{action=...}` counter increments on each decision. |

**Fail signal:** generation happens BEFORE the cost gate runs (visible
in the trace: a `usage_records` row exists but no `budget_decisions_total`
metric was emitted). The gate must run after retrieval, before generation.

---

### F6. Audit dual-write + immutability

**ADR-0016 + Pillar #6.** Every privileged action is dual-written to
Postgres `audit_events` AND object storage (S3 Object Lock COMPLIANCE
/ GCS locked retention).

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_audit_dual_write.py apps/api/tests/unit/test_audit_reconciliation.py` — 5 + 16 tests covering primary-fail propagation, secondary-fail isolation, S3 key format, JSON serialization, diff math, backfill cap, idempotency. |
| Manual | Issue 5 `/query` requests against `make up`; check both `audit_events` table (`SELECT count(*) FROM audit_events WHERE event_type = 'query.executed'`) AND the MinIO bucket (`mc ls local/sentinelrag-audit/`) — counts must match. |
| Reconciliation | The Temporal `AuditReconciliationWorkflow` runs daily. Locally trigger it via `python -m sentinelrag_worker.scripts.register_audit_schedule` and inspect drift metrics. |
| Immutability | Try `mc rm local/sentinelrag-audit/<some-key>` → MinIO permits it locally (Object Lock requires real S3); on AWS this would be denied even by root. |

**Fail signal:** a `query.executed` event in Postgres but not in the
audit bucket (or vice versa) — drift means dual-write order or error
handling is broken.

---

### F7. Document ingestion via Temporal

**Phase 2.** `IngestionWorkflow` + 8 idempotent activities: download
→ parse → chunk (3 strategies) → embed → finalize.

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_chunkers.py` — 10 tests covering semantic, sliding-window, structure-aware. |
| Manual | `make up && make seed`. `POST /api/v1/documents` with a multipart upload. Watch via Temporal UI (`http://localhost:8233`) — workflow should complete in 30-60 s for a small PDF. Verify chunks appear: `SELECT count(*) FROM document_chunks WHERE document_id = '<uuid>'`. |
| Resilience | Kill the worker mid-ingestion (`docker compose kill temporal-worker`). Restart it. Workflow should resume from the last completed activity (Temporal at-least-once semantics; activities are idempotent). |

**Fail signal:** workflow stuck in `Running` for >10 min, or chunk
count is zero. Check worker logs for activity errors.

---

### F8. Evaluation framework

**ADR-0019 + Phase 4.** Versioned datasets, four custom evaluators, eval
runs orchestrated via Temporal.

| Layer | What to run |
|---|---|
| Unit | `uv run pytest apps/api/tests/unit/test_evaluators.py` — 11 tests covering all four evaluators' edge cases. |
| Manual | `POST /api/v1/eval/datasets` to create a dataset; add cases via `POST /eval/datasets/{id}/cases`; trigger a run via `POST /eval/runs`. Inspect rolled-up scores via `GET /eval/runs/{id}`. |
| Comparison | `uv run python tests/performance/evals/compare.py --compare hybrid-vs-vector ...` — see `tests/performance/evals/README.md`. |

**Fail signal:** an evaluator returns a score outside `[0, 1]` — clamp
in the evaluator, not the consumer.

---

### F9. Frontend dashboard

**Phase 5.** Next.js 15 App Router, NextAuth + Keycloak, query
playground with SSE-driven trace stream.

| Layer | What to run |
|---|---|
| Unit | `cd apps/frontend && npm run test` — 5 vitest tests covering bearer auth forwarding, query serialization, error envelope unwrapping, multipart upload. |
| E2E | `cd apps/frontend && npm run test:e2e` — 15 Playwright tests; deterministic mocked-API specs cover the dashboard, collections, documents, query, prompts, evaluations, settings, audit, and usage surfaces. API-dependent specs skip cleanly when backend not reachable. |
| Manual | `make up && make api && cd apps/frontend && npm run dev`. Open `http://localhost:3000`. Hit `/query-playground`. Submit a query — the trace pane should update in real time via SSE (look for `event: trace` frames in DevTools network panel). |

**Fail signal:** the trace pane shows nothing → either SSE is buffering
(check `X-Accel-Buffering: no` header) or the polling fallback isn't
kicking in after 4 s.

---

### F10. Local stack health

**Phase 0 / `make up`.**

```bash
make up
# Wait ~30s for healthcheck convergence.

# Each component should be reachable:
curl -fsS http://localhost:8000/api/v1/health     # API
curl -fsS http://localhost:8080/realms/master     # Keycloak
curl -fsS http://localhost:9100/minio/health/live # MinIO
nc -zv localhost 11434                            # Ollama
nc -zv localhost 7233                             # Temporal frontend (gRPC)
nc -zv localhost 15432                            # Postgres (host port; container is 5432)
nc -zv localhost 6380                             # Redis (host port; container is 6379)
curl -fsS http://localhost:9090/-/healthy         # Prometheus
curl -fsS http://localhost:3001/api/health        # Grafana
```

**Fail signal:** `nc -zv localhost 6379` succeeds → another Redis is
running on your host (the local-dev quirk documented in ADR-0001 /
docker-compose.yml). Confirm `compose.yml` maps to host port 6380.

---

### F11. Migrations are RLS-aware + reversible

**Phase 1 / ADR-0008.** Every migration touching a tenant-owned table
must include the RLS policy. Migrations are hand-written, never
autogenerated.

| Layer | What to run |
|---|---|
| Manual | `make db-upgrade` then `make db-downgrade` then `make db-upgrade` again. Final state must match the first apply (`SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'` constant across the three runs). |
| Lint | `grep -l 'ALTER TABLE.*ENABLE ROW LEVEL SECURITY' migrations/versions/*.py` — every tenant-owned table's creation migration should hit. |

**Fail signal:** a migration with `op.create_table(... 'tenants'...)` but
no `op.execute("ALTER TABLE ... ENABLE ROW LEVEL SECURITY")` — that's
a missing isolation policy.

---

### F12. Helm chart renders cleanly across all five overlays

```bash
cd infra/helm/sentinelrag
helm dependency build  # one-time after a fresh checkout
for f in values.yaml values-dev.yaml values-gcp-dev.yaml values-prod.yaml values-local.yaml; do
  echo "=== $f ==="
  helm lint . -f $f
  helm template release-test . -f $f > /dev/null
done
# All five must lint clean and render without errors.
```

**Fail signal:** `helm template` fails with `nil pointer evaluating ...`
on a `_helpers.tpl` invocation — usually a missing key in the values
overlay (e.g. `serviceAccount.annotations` is required-by-template but
optional-by-schema).

---

### F13. Resilience under load — k6 + Chaos Mesh

**ADR-0027 + Phase 8 Slice 3.** k6 scenarios are SLO-bound; Chaos Mesh
experiments carry hypotheses in their YAML headers.

| Layer | What to run |
|---|---|
| Smoke | `k6 run -e SENTINELRAG_AUTH_TOKEN=dev -e SENTINELRAG_COLLECTION_IDS=<uuid> tests/performance/k6/smoke.js` — 30 s, 0.5 rps. Must pass thresholds. |
| Baseline | `tests/performance/k6/baseline.js` — 13 m, 5 rps. Run pre-release. |
| Spike | `tests/performance/k6/spike.js` — exercises HPA autoscaler. |
| Soak | `tests/performance/k6/soak.js` — 1 hour at 3 rps; catches memory leaks. |
| Chaos game-day | `kubectl apply -f infra/chaos/workflows/game-day.yaml` while running `baseline.js` against the same cluster. The k6 thresholds ARE the assertions. |

**Fail signal:** a chaos experiment passes (no pod crashes) but the
k6 baseline fails the SLO threshold → the resilience hypothesis broke.
Read the `Hypothesis:` block in the experiment manifest and audit the
relevant code path.

---

### F14. Daily backup verification

**ADR-0028.** `scripts/dr/verify-backups-{aws,gcp}.sh` polls RDS /
Cloud SQL snapshots, S3 / GCS bucket versioning, Object Lock /
retention policy. CI workflow runs daily at 06:37 UTC.

```bash
# AWS — needs aws CLI authenticated.
SENTINELRAG_PREFIX=sentinelrag-dev bash scripts/dr/verify-backups-aws.sh

# GCP — needs gcloud authenticated.
SENTINELRAG_GCP_PROJECT=<project> SENTINELRAG_PREFIX=sentinelrag-dev \
  bash scripts/dr/verify-backups-gcp.sh
```

**Fail signal:** the script exits 0 but the `ok: false` field appears in
its JSON output — a bug in the script's exit-code threading. Fix the
script; don't paper over the failure.

---

### F15. DR drills (quarterly)

See [`disaster-recovery.md`](disaster-recovery.md) for the eight failure
scenarios and the drill cadence. Each drill writes a one-pager to
`docs/operations/dr-drills/YYYY-MM-DD-<scope>.md` documenting actual
RTO, surprises, follow-ups. (Directory created on first drill.)

---

## Cross-environment summary

| Feature | Local stack | Dev cluster | Prod cluster |
|---|---|---|---|
| Unit tests | `pytest -m unit` | n/a | n/a |
| Integration tests | `pytest -m integration` | n/a (run pre-deploy) | n/a |
| Frontend e2e | Playwright (auto-skips API-dependent) | Playwright against real API | n/a |
| RLS + RBAC manual | dev token | Keycloak token | Keycloak token |
| Cost gate | seeded budget | seeded budget | real budget |
| Audit immutability | MinIO (no Object Lock) | S3 Object Lock (real) | S3 Object Lock (real) |
| k6 smoke | local | live (CI gate via `perf-smoke.yml`) | not run |
| Chaos game-day | not applicable | quarterly | not run |
| DR drill | not applicable | quarterly | semi-annually |
| Daily backup verify | not applicable | daily CI cron | daily CI cron |

---

## Cross-references

- [`local-development.md`](local-development.md) — bringing the local stack up
- [`deployment-aws.md`](deployment-aws.md) / [`deployment-gcp.md`](deployment-gcp.md) — getting to a dev cluster
- [`cluster-bootstrap.md`](cluster-bootstrap.md) — bootstrap order
- [`disaster-recovery.md`](disaster-recovery.md) — recovery procedures + drills
- [`tests/performance/k6/README.md`](../../../tests/performance/k6/README.md) — k6 details
- [`tests/performance/evals/README.md`](../../../tests/performance/evals/README.md) — eval comparison harness
- [`infra/chaos/README.md`](../../../infra/chaos/README.md) — Chaos Mesh experiment matrix
- [`AGENTS.md`](../../../AGENTS.md) — Codex session checklist, locked stack, architectural pillars, footguns
