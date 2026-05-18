# ADR-0031: Retrieval-service extracted to a real HTTP workload

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** retrieval, deployment, microservices, supersession

## Context

[ADR-0021](0021-retrieval-embedded-v1.md) decided retrieval would live as
library code inside the API for v1, with the
[`apps/retrieval-service/`](../../../apps/retrieval-service) folder
reserved as a Phase-7 extraction target. The 2026-05-16 architecture
review (finding #5, recorded in
[`reviews/2026-05-16-architect-review.md`](../reviews/2026-05-16-architect-review.md))
flagged this as the highest-leverage remaining "is it real?" question.

Two paths were on the table after R1.S1 shipped the `RetrievalClient`
Protocol:

- **Option A** — extract the workload for real: HTTP wrapper,
  service-to-service auth, NetworkPolicy, Helm workload, benchmark.
- **Option B** — delete the shell directory and declare the embed model
  permanent.

The 2026-05-16 decisions log entry locked Option A. The portfolio signal
of "real microservice extracted, with benchmark + the operational
artifacts that come with it" was judged worth the one extra pod's
operational cost. R4 is the implementation.

## Decision

Retrieval is now a workload with its own:

- **Code:** `apps/retrieval-service/sentinelrag_retrieval_service/`,
  fleshed out with a real `POST /v1/retrieve` route that mirrors the
  `RetrievalClient` Protocol shape from R1.S1. Re-uses the shared
  retrieval library — no logic duplication.
- **Contracts:** `sentinelrag_shared.contracts.retrieval` gained
  `RetrieveRequest`, `RetrieveResponse`, `AuthContextDTO`, and
  `EmbeddingUsageDTO`. The diagnostic `Rrf*` contracts stay for
  backward compatibility but new callers should use the live shape.
- **Transport switch:** `Settings.retrieval_transport` (env
  `RETRIEVAL_TRANSPORT`) on the API service selects between
  `in-process` (the legacy library path) and `http` (the new
  network-bound path). The orchestrator's existing
  `RetrievalClient | None` constructor argument accepts either impl;
  the lifecycle's `_build_retrieval_client` materializes the right one.
- **HTTP client:** `HttpRetrievalClient` in
  `apps/api/app/services/rag/client.py`. httpx-based; retries
  `502/503/504` and transient connection errors at most twice; refuses
  to retry timeouts or `4xx`; exposes `aclose()` for the lifecycle's
  shutdown path.
- **Service-to-service auth:** a shared bearer secret
  (`RETRIEVAL_SERVICE_TOKEN`) is sent in the `Authorization` header.
  The retrieval-service refuses with `503` when its `SERVICE_TOKEN`
  env is unset, so an accidentally-public deploy fails loud rather
  than silently exposing retrieval to unauthenticated callers.
- **K8s topology:** `infra/helm/sentinelrag/templates/retrieval/`
  ships a Deployment + Service + ConfigMap + ExternalSecret + HPA +
  PDB + ServiceAccount + NetworkPolicy. The NetworkPolicy ingress
  rule selects pods with
  `app.kubernetes.io/component=api` — only the API workload can talk
  to retrieval. Egress remains broad (DNS + cluster-internal),
  matching the API workload's policy; tighter egress is deferred to
  the Phase 8 hardening pass.

The **default transport** stays `in-process` until the R4.S6 benchmark
verifies the p95 budget for the HTTP path. The Helm chart sets
`RETRIEVAL_TRANSPORT=http` in `values.yaml`'s `api.envFromConfigMap` so
deployed environments exercise the extracted path; local docker-compose
and unit tests fall back to in-process via the default Settings value.

Naming note: the env var is `RETRIEVAL_TRANSPORT`, not `RETRIEVAL_MODE`
as the original remediation plan said. `RETRIEVAL_MODE=hybrid` already
exists in `.env.example` as a documentation hint for the per-request
retrieval mode (`bm25 | vector | hybrid`); reusing the name would have
crossed those wires.

## Consequences

### Positive

- Closes the "shell vs. live" ambiguity that ADR-0021 left open.
  `apps/retrieval-service/` is now a real workload with a real
  contract, real auth, and real K8s topology.
- The HTTP retrieval path is the first cross-service REST call in
  SentinelRAG, validating ADR-0009 (REST + Pydantic, not gRPC). Adds
  observability via OTel httpx instrumentation.
- The retrieval workload can now scale independently of the API.
  Different HPA target, different node selector if a GPU-bound
  reranker lands later.
- The `embedding_usage` carry-over from R3.S1 survives the network
  hop — `EmbeddingUsageDTO` is a first-class field on the response
  so the API's budget gate + persistence stage stay correct in both
  transports.
- RBAC at retrieval time (architecture pillar #1) is preserved.
  `AuthContextDTO` flows in the body; the retrieval-service re-binds
  `app.current_tenant_id` on the SQLAlchemy session so Postgres RLS
  is the second layer of defense beneath the application-level
  AccessFilter.

### Negative

- One more pod to run. One more Dockerfile, one more set of probes,
  one more ExternalSecret. Operational surface grew.
- The R4.S6 benchmark is **not** in this ADR — it requires live infra
  (k6 against a real cluster). Until that result lands, the default
  transport stays `in-process` even though the HTTP path is fully
  wired. The follow-up updates this ADR's "Benchmark" section in a
  separate PR.
- Service-to-service auth is a shared bearer token, not mTLS / Keycloak
  service accounts. We accept this for the v1 demo; the production
  upgrade path is in "Notes on the design docs".

### Neutral

- The diagnostic `/health`, `/healthz`, `/capabilities`, and
  `/rrf-merge` endpoints on the retrieval-service are kept as-is.
  `/capabilities` advertises the real backend list only when
  `SERVICE_TOKEN` is configured, so unauthenticated probes see the
  diagnostic surface only.

## Alternatives considered

### Option A — Extract for real *(chosen)*
- See above.

### Option B — Delete the empty `apps/retrieval-service/` folder; embed forever
- **Pros:** Lower operational complexity. Fewer Dockerfiles + ESO + HPA
  resources.
- **Cons:** Loses the "real microservice" portfolio signal. Locks in
  monolith. The same trade-off ADR-0021 already weighed and tentatively
  resolved in favor of "extract when we benchmark."
- **Rejected because:** The remediation plan's 2026-05-16 decisions log
  picked Option A.

## Trade-off summary

| Dimension | Extract (this) | Embed (ADR-0021) |
|---|---|---|
| Pods to operate | 2 (api, retrieval) | 1 (api) |
| Retrieval scaling | Independent HPA | Coupled to api HPA |
| GPU upgrade path | Move retrieval pods only | Touches api workload |
| Failure-mode count | More (network) | Fewer |
| Portfolio signal | High (real extraction + benchmark) | Medium |
| Per-query latency (no GPU) | +5–15ms RTT | 0 |

## Notes on the design docs

This ADR **supersedes ADR-0021**. ADR-0021's status flips to
"Superseded by ADR-0031" in the same PR. The substantive decision in
0021 (start embedded, extract when justified) is honored exactly —
this ADR documents the extraction step it predicted.

Production upgrade path for service-to-service auth (recorded here for
the future hardening ADR):

1. Issue per-workload Keycloak service accounts (sentinelrag-api,
   sentinelrag-retrieval). Each gets a client credentials grant.
2. The API service exchanges its credentials for a JWT and sends it as
   the `Authorization: Bearer` header on retrieval calls.
3. The retrieval-service uses the same `JWTVerifier` it already
   imports from `sentinelrag_shared.auth` to verify, against the same
   JWKS cache the API uses.
4. The shared bearer secret env (`SERVICE_TOKEN`) is removed.

The benchmark report (R4.S6) is regenerated by the existing harness at
`tests/performance/evals/compare.py` and `tests/performance/k6/` —
hand-edited numbers in this ADR are not allowed (ADR-0029).

## Benchmark scaffolding (2026-05-17)

R4.S6 (the benchmark itself) requires a live cluster, so the
numbers don't live in this ADR yet. The *harness* to produce them
is wired and ready:

- `tests/performance/evals/compare.py` gained a
  `retrieval-transport` comparison config + matching
  `--before-base-url` / `--after-base-url` CLI flags. The two sides
  send identical request bodies; the difference lives on the server
  (`RETRIEVAL_TRANSPORT` env). Output goes to
  `docs/operations/eval-report.md` via the existing renderer.
- `tests/performance/k6/transport-compare.js` is a thin
  baseline-shaped scenario that tags every metric with the
  configured `transport` label. Operator runs it twice — once per
  transport — and the two summary JSONs feed a follow-on summarizer
  step.
- `docs/operations/runbooks/retrieval-benchmark.md` walks the
  procedure end-to-end: stand up two Helm releases differing only
  in `RETRIEVAL_TRANSPORT`, run both harnesses, summarize, commit
  the artifacts, then append a "Benchmark result (YYYY-MM-DD)"
  section to this ADR.

The decision rule for flipping the default transport stays as
above: the HTTP path stays the chart's default unless the live
benchmark shows p95 over the
`tests/performance/k6/lib/config.js::SLO.queryP95Ms` budget.

When the first live run completes, this section gets a
"Benchmark result (YYYY-MM-DD)" entry that links to the generated
reports and the operator's interpretation.

## References

- [ADR-0009](0009-rest-not-grpc.md) — REST + Pydantic between services
  (validated by this extraction)
- [ADR-0021](0021-retrieval-embedded-v1.md) — predecessor; superseded
  by this ADR
- [Architecture review 2026-05-16](../reviews/2026-05-16-architect-review.md)
  — finding #5 (retrieval-service half-done)
- [REMEDIATION_PLAN.md § Phase R4](../REMEDIATION_PLAN.md)
- [ADR-0029](0029-portfolio-polish.md) — harness-generated metrics; no
  hand-edited eval/cost numbers
