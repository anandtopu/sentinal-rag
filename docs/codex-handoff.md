# Codex Handoff

Last updated: 2026-05-15

## Current State

The worktree contains uncommitted refactor/hardening changes for two service passes:

1. `retrieval-service`
2. `temporal-worker`

No new ADR was added because both passes stay inside existing architecture decisions:

- ADR-0021 for retrieval-service extraction shape.
- ADR-0007 for Temporal as the durable workflow engine.

## Retrieval-Service Changes

- Added shared retrieval REST contracts in `packages/shared/python/sentinelrag_shared/contracts/retrieval.py`.
- Exported the new contracts from `sentinelrag_shared.contracts`.
- Updated `apps/retrieval-service/sentinelrag_retrieval_service/main.py` to use shared contracts for `/rrf-merge` and `/capabilities`.
- Removed the empty legacy `apps/retrieval-service/app/__init__.py` package stub.
- Hardened shared retrieval behavior:
  - `merge_with_rrf` validates `rrf_k > 0`.
  - `merge_with_rrf` rejects candidates with rank `< 1`.
  - `AccessFilter` now grants tenant-visible collections by default for read only, not write/admin.
  - Requested collection IDs are cast as `uuid[]` in SQL predicates.
- Added/updated tests in:
  - `apps/retrieval-service/tests/unit/test_retrieval_service_app.py`
  - `apps/api/tests/unit/test_retrieval_regressions.py`

## Temporal-Worker Changes

- Added `apps/temporal-worker/sentinelrag_worker/settings.py` to centralize worker runtime configuration.
- Updated worker entrypoint to use shared settings for logging, telemetry, Temporal host/namespace, and task queues.
- Updated ingestion, evaluation, and audit reconciliation activities to share one DB URL default.
- Fixed local worker DB fallback to match the repo Docker stack: `localhost:15432`.
- Hardened audit reconciliation schedule registration:
  - validates integer env vars
  - validates boolean env vars
  - enforces positive interval and non-negative max-backfill
  - deduplicates tenant IDs
  - reads Temporal host/namespace/task queue from shared worker settings
- Added tests in:
  - `apps/temporal-worker/tests/unit/test_worker_settings.py`
  - `apps/temporal-worker/tests/unit/test_audit_schedule_registration.py`

## Verification Already Run

Retrieval pass:

```powershell
$env:UV_CACHE_DIR='.uv-cache'; uv run ruff check apps/retrieval-service apps/api/tests/unit/test_retrieval_regressions.py apps/api/tests/unit/test_opensearch_keyword_search.py packages/shared/python/sentinelrag_shared/contracts/__init__.py packages/shared/python/sentinelrag_shared/contracts/retrieval.py packages/shared/python/sentinelrag_shared/retrieval/access_filter.py packages/shared/python/sentinelrag_shared/retrieval/hybrid.py
$env:UV_CACHE_DIR='.uv-cache'; uv run pytest apps/retrieval-service/tests/unit/test_retrieval_service_app.py apps/api/tests/unit/test_retrieval_regressions.py apps/api/tests/unit/test_opensearch_keyword_search.py -q
```

Results:

- Ruff clean.
- Retrieval-focused tests: `36 passed`.
- Full unit suite after retrieval pass: `176 passed`.

Temporal-worker pass:

```powershell
$env:UV_CACHE_DIR='.uv-cache'; uv run ruff check apps/temporal-worker/sentinelrag_worker apps/temporal-worker/tests/unit apps/api/tests/unit/test_temporal_worker_coverage.py
$env:UV_CACHE_DIR='.uv-cache'; uv run pytest apps/temporal-worker/tests/unit apps/api/tests/unit/test_temporal_worker_coverage.py apps/api/tests/unit/test_evaluation_regressions.py -q
$env:UV_CACHE_DIR='.uv-cache'; uv run pytest -m unit -q
```

Results:

- Ruff clean.
- Worker-focused tests: `22 passed`.
- Full unit suite after worker pass: `182 passed`.
- Only warning: existing Windows `.pytest_cache` access warning.

## Current Git Status At Handoff

Expected changed files:

- `apps/api/tests/unit/test_retrieval_regressions.py`
- `apps/retrieval-service/app/__init__.py` deleted
- `apps/retrieval-service/sentinelrag_retrieval_service/main.py`
- `apps/retrieval-service/tests/unit/test_retrieval_service_app.py`
- `apps/temporal-worker/sentinelrag_worker/activities/audit_reconciliation.py`
- `apps/temporal-worker/sentinelrag_worker/activities/evaluation.py`
- `apps/temporal-worker/sentinelrag_worker/activities/ingestion.py`
- `apps/temporal-worker/sentinelrag_worker/main.py`
- `apps/temporal-worker/sentinelrag_worker/scripts/register_audit_schedule.py`
- `apps/temporal-worker/sentinelrag_worker/settings.py`
- `apps/temporal-worker/tests/unit/test_audit_schedule_registration.py`
- `apps/temporal-worker/tests/unit/test_worker_settings.py`
- `packages/shared/python/sentinelrag_shared/contracts/__init__.py`
- `packages/shared/python/sentinelrag_shared/contracts/retrieval.py`
- `packages/shared/python/sentinelrag_shared/retrieval/access_filter.py`
- `packages/shared/python/sentinelrag_shared/retrieval/hybrid.py`

Recommended next step: review the diff as a combined service-hardening patch, then commit if the scope looks right.
