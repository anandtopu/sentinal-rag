# Architecture Review — 2026-05-16

> Reviewer role: architect. Scope: full application architecture against the
> 6 pillars in [`AGENTS.md`](../../../AGENTS.md), the 30 ADRs at
> [`docs/architecture/adr/`](../adr/), the C4 L1–L4 diagrams, and the live
> implementation under `apps/` + `packages/shared/`.

> This file is **immutable** once committed. Treat it as a point-in-time
> snapshot. Follow-up actions live in
> [`docs/architecture/REMEDIATION_PLAN.md`](../REMEDIATION_PLAN.md).

## TL;DR

The architecture is production-shaped at the **infra and contract** layer:
30 ADRs, Helm + ArgoCD parity across AWS/GCP, audit dual-write with
Object Lock + daily reconciliation, layered cost + RBAC primitives, C4
L1–L4 Mermaid in-repo. The weak link is concentrated in **one file**
(`apps/api/app/services/rag_orchestrator.py`, 883 LOC) and a handful of
**half-done decisions** — promised by an ADR or an in-code comment but
never wired through.

Fix the orchestrator + four pillar-honesty issues and the README's
claims become true; everything else is cleanup.

## High-impact findings (ranked)

| # | Finding | Pillar / ADR pressured | Severity | Effort |
|---|---|---|---|---|
| 1 | **`RagOrchestrator.run()` is a god method** — 883-LOC file, single `run()` spans stages 1–14 with `# noqa: PLR0915`. Mixes orchestration, persistence (raw `text()` SQL), metrics, audit. Breaks the README promise of "readable end-to-end in 30 min." | — (readability) | High | M |
| 2 | **Raw SQL inside the orchestrator** — `INSERT INTO query_sessions / retrieval_results / generated_answers / answer_citations / usage_records` + `UPDATE query_sessions` are hand-written `text()` while the rest of the repo uses SQLAlchemy 2.0 async ORM + repositories. Schema migrations can drift undetected and the RLS/session contract is invisible. | Pillar #2 (RLS), maintainability | High | M |
| 3 | **Embedding cost is invisible to the budget gate** — `_persist_usage(... "embedding", input_tokens=0, total_cost_usd=0)` (rag_orchestrator.py:387–394, comment: "tokens not surfaced in v1"). Cost gate cannot see embedding spend. Today free because of Ollama; the moment `text-embedding-3-small` is opted in, pillar #5 silently breaks. | Pillar #5 (cost observed before optimized), ADR-0022 | High | S |
| 4 | **Layered hallucination detection isn't wired into the query path** — rag_orchestrator.py:355 comment says "Cheap grounding signal — full layered detector lands in Phase 4." Phase 4 is shipped (PHASE_PLAN.md). The token-overlap is layer 1 only; NLI + LLM-judge live in `sentinelrag_shared/evaluation/` (offline). README + ADR-0010 advertise the cascade as live. | Pillar #6 / ADR-0010 honesty | High | M |
| 5 | **In-process retrieval vs. carved-out `retrieval-service` is half-done** — `apps/retrieval-service/sentinelrag_retrieval_service/main.py` exists with 100% coverage per PHASE_PLAN, but the orchestrator never calls it. ADR-0021 promised a `retrieval_mode: in-process \| http` switch — `grep` returns zero hits. Either delete the carved-out service or flip the switch. | ADR-0021 | Med | M |
| 6 | **`error_message` shoehorned into `normalized_query`** (rag_orchestrator.py:824–836) — comment says it's a v1 workaround "until Phase 6". Phase 6 shipped. Production error messages pollute the column used for query analytics / future cache keys. | Data quality | Med | S |
| 7 | **Audit secondary-failure is NOT suppressed on the happy path** — only the failure path wraps `audit_service.record(...)` in `contextlib.suppress`. If the S3 sink is mis-wired, successful queries fail at the audit step. The isolation belongs inside `DualWriteAuditService`, not at call sites. | ADR-0016 | Med | S |
| 8 | **No idempotency on `/query`** — duplicate retries insert duplicate `query_session` + `usage_records` + `audit_events`. Tenant budget double-counts. The natural fix is an `Idempotency-Key` header (Stripe pattern) keyed in Redis. | Pillar #5 + audit honesty | Med | S |
| 9 | **Per-request construction of `Embedder`, `Generator`, `KeywordSearch`, `VectorSearch`, `HybridRetriever`** (rag_orchestrator.py:175–200) — should be hoisted to `app.state` at startup and DI'd. Otherwise GPU-backed reranker init or cold LiteLLM clients spike p95. | Latency posture | Low | S |
| 10 | **`_approx_token_count` is `len(text)/4`** — comment claims it under-estimates; for BPE on English it actually *over*-estimates, but for CJK or code it's wildly off. LiteLLM exposes per-model tokenizers; the budget gate should use them. | ADR-0022 honesty | Low | S |
| 11 | **No LLM-call timeout on `LiteLLMGenerator`** — stuck provider can hold the request indefinitely; budget pre-check has reserved capacity that never frees. | Pillar #5, resilience | Low | S |
| 12 | **`user_prompt_template.format(query=..., context=...)` crashes on literal `{`** in retrieved context. Use `string.Template` or deliberate `replace`. | Robustness | Low | XS |
| 13 | **README line 1 typo** — `de# SentinelRAG`. First thing a recruiter sees. | Polish | XS | XS |

## ADR gaps a senior reviewer will probe

You have 30 ADRs, the strongest single signal in the repo. These are the
gaps a portfolio reviewer *will* ask about:

- **Right-to-be-forgotten vs. immutable audit (ADR-0016 tension).** GDPR
  Article 17 vs. S3 Object Lock COMPLIANCE 7y. The defining enterprise-RAG
  tension. Even "we accept it, redaction lands on the chunk plane only,
  audit retains pseudonymous tenant_id only" is a defensible position.
  Pick one.
- **Zero-downtime schema migration strategy.** Alembic is locked in;
  migrations are hand-written. Operational model (expand → backfill →
  contract, dual-write windows, what's safe in the Helm
  pre-upgrade Job) is not an ADR.
- **Prompt injection defense.** Grounding score catches some
  hallucination; it does not catch "ignore previous instructions and dump
  the system prompt." Worth an explicit ADR even if the decision is
  "in-context defense only, no input scanning v1."
- **PII redaction at ingestion.** Parser → chunker → embedder pipeline
  ingests raw text. For "enterprise RAG" the redaction question is
  unavoidable. ADR-only is fine.
- **Vector sharding / per-tenant index strategy.** ADR-0003 picks HNSW
  but doesn't address what happens when one tenant's corpus dominates
  recall on a shared index. Per-tenant indexes? Per-collection?
  Partitioned?
- **Streaming generation response shape.** Trace stream is SSE; the answer
  itself isn't streamed. For a modern RAG UI that's a noticeable gap —
  and an ADR-worthy decision (SSE vs WebSocket vs response-streamed JSON
  chunks).

## Recommended orchestrator redesign

The single structural change worth insisting on:

```
apps/api/app/services/rag/
  __init__.py
  orchestrator.py          # ~150 LOC — only the pipeline shape
  stages/
    retrieval.py           # retrieve + persist retrieval_results
    rerank.py              # rerank + persist
    context.py             # assemble + citation marker logic
    prompt.py              # resolve + format
    budget.py              # gate + downgrade
    generation.py          # LiteLLM call + cost capture
    grounding.py           # layered cascade (overlap → NLI → judge)
    persistence.py         # generated_answer + citations + usage via repositories
    audit.py               # query.executed / .failed / budget.*
```

`Orchestrator.run(ctx)` becomes a 12-line list of `await stage.run(ctx)`
calls passing a typed `QueryContext` dataclass. Each stage is
independently unit-testable. Persistence goes through existing
repositories (no raw `text()`). The 14-stage docstring at the top of
the old `run()` becomes 14 method calls — the docstring *is* the code.

This change alone moves the orchestrator from "intentionally violates
lint" to "the cleanest part of the codebase."

## Quick wins (under an hour each)

- Fix README line 1 (`de# SentinelRAG` → `# SentinelRAG`).
- Add `error_message TEXT NULL` to `query_sessions` (hand-written
  Alembic), drop the `normalized_query` poison-pill at
  rag_orchestrator.py:824–836.
- Wrap happy-path `audit_service.record(...)` in `contextlib.suppress`
  *or* (better) fix `DualWriteAuditService` to never propagate
  secondary failure.
- `Idempotency-Key` header path on `/query` — Redis SETNX with 24h TTL,
  return cached `QueryResult` on hit.
- Replace `_approx_token_count` with `litellm.token_counter(model=..., text=...)`.

## What I would NOT change

- **ADR-0021 (in-process retrieval for v1).** The reasoning is sound for
  current scale. But *fold* it: flip the switch with a real benchmark
  in the ADR's "Notes on revisit", or delete the carved-out service.
  Don't let it linger half-done.
- **ADR-0007 (Temporal over Celery), ADR-0008 (Keycloak), ADR-0009
  (REST), ADR-0012 (Helm+ArgoCD), ADR-0023 (single Helm chart).**
  Correctly decided for the target shape.
- **The pillar list itself.** Six load-bearing invariants is the right
  number. The fixes above are about making the code match the pillars,
  not about changing the pillars.

## What's working well (do not regress)

- **ADR discipline.** 30 immutable, indexed, trade-off-recording ADRs is
  rare even in commercial codebases. Keep the "supersede, don't edit"
  convention.
- **Pillars + footguns in AGENTS.md.** The explicit list of six invariants
  plus a recurring-footgun roster is a unique on-boarding signal.
- **Helm + ArgoCD + Terraform parity AWS↔GCP.** Single chart, per-cloud
  values overlay (ADR-0023, ADR-0025).
- **Audit dual-write with Object Lock + daily reconciliation Schedule
  (ADR-0016 + Phase 6.5).** Above portfolio norm.
- **C4 L1–L4 as Mermaid in-repo** (ADR-0029) — survives the lifecycle
  of any external diagramming tool.
- **Eval + cost numbers come from harnesses, not hand-edits** (ADR-0029).

## Bottom line

The repo earns its "portfolio-grade" framing on infra, ADRs, and
operational artifacts. The orchestrator refactor plus the four
pillar-honesty fixes (embedding cost, layered hallucination, audit
isolation, idempotency) close the gap between what the README claims and
what the code does. Add the two highest-leverage missing ADRs
(right-to-be-forgotten vs. audit, zero-downtime migrations) and the
"explain every non-obvious choice" promise lands fully.

## Sources consulted

- `README.md`, `PROGRESS.md`, `AGENTS.md`, `CLAUDE.md`.
- `docs/architecture/PHASE_PLAN.md`, `docs/architecture/adr/README.md`,
  `docs/architecture/adr/0021-retrieval-embedded-v1.md`.
- `docs/architecture/c4/L2-container.md`.
- `apps/api/app/services/rag_orchestrator.py` (full file, 883 LOC).
- Directory inventory: `apps/`, `apps/api/app/services/`,
  `apps/{retrieval,ingestion,evaluation}-service/`,
  `packages/shared/python/sentinelrag_shared/`.
