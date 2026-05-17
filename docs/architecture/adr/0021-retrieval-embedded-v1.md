# ADR-0021: Retrieval is in-process for v1; extract to retrieval-service in Phase 7

- **Status:** Superseded by [ADR-0031](0031-retrieval-service-extraction.md)
- **Date:** 2026-04-27
- **Superseded on:** 2026-05-17
- **Tags:** retrieval, deployment, microservices, scope

## Context

The folder structure (`apps/retrieval-service/`) and ADR-0009 imply retrieval is its own microservice that the API gateway calls over REST. ADR-0009 commits to REST + Pydantic between services. Building it as a separate service from day one has real costs:

- Two deployments to operate locally (one more `make worker`-style target).
- Two sets of Dockerfiles, healthchecks, OpenTelemetry init.
- Cross-service Pydantic contracts package gets extended for retrieval (already exists for ingestion per Phase 2.9).
- Each `query` request hops API → retrieval-service → DB, adding ~10ms RTT in dev and a real failure mode.

At v1 scale (single-tenant demo, <100 QPS) these costs aren't justified by the benefits (independent scaling, isolation, separate deploy cadence). The interface — `HybridRetriever`, `KeywordSearch`, `VectorSearch`, `Reranker` — is what matters; whether it crosses a network boundary is a deployment topology decision.

## Decision

For v1 (Phases 3–6):

- Retrieval implementations live as **library code** in `packages/shared/python/sentinelrag_shared/retrieval/`.
- The `RagOrchestrator` in `apps/api` imports and calls them in-process.
- The `apps/retrieval-service/` directory remains in the folder structure but stays empty (placeholder for Phase 7).
- The interface is the same one a future HTTP wrapper would expose; the contract is captured by the protocols (`KeywordSearch`, `VectorSearch`, `Reranker`).

In Phase 7 (production deployment), if benchmarks demand it OR if we want to scale the retrieval workload independently (the rerank stage is the GPU-needing one), we **extract**: a thin `apps/retrieval-service/sentinelrag_retrieval/` HTTP wrapper imports the same shared library and exposes it via REST. Cross-service contracts get added to `sentinelrag_shared.contracts.retrieval`. The orchestrator gets a configuration switch (`retrieval_mode: in-process | http`) to choose the path.

## Consequences

### Positive

- One fewer service to operate in v1; Docker compose simpler; faster iteration during retrieval R&D.
- The interface boundary stays clean — when we extract, we add HTTP plumbing, not refactor the call sites.
- The API service can import and unit-test retrieval directly without spinning up a second process.

### Negative

- Loses the "I deployed a real microservice" signal in Phase 3. Recovered in Phase 7.
- The `apps/retrieval-service/` directory sits empty for several phases. Documented in this ADR so it's not interpreted as a missing implementation.
- Adding a GPU-bound reranker (bge-reranker on a g4dn) into the same pod as the API service is awkward. We accept this for v1 (CPU-mode reranker is acceptable at low QPS); when we add GPU, we extract.

### Neutral

- The "retrieval is a service" claim is still true at the *architectural* level — the protocol/contract design is what makes it portable.

## Alternatives considered

### Option A — Separate retrieval-service from day one (per spec)
- **Pros:** Cleaner topology; matches the C4 diagrams; "real microservice" signal sooner.
- **Cons:** Above. Mostly the cost is *time*, which we want for retrieval-quality work, not service-plumbing work.
- **Rejected because:** Interface fidelity is not compromised; the topology is recoverable in Phase 7.

### Option B — Library-only forever, drop the retrieval-service folder
- **Pros:** Simpler; one less aspirational empty folder.
- **Cons:** When we eventually want to scale rerank independently OR run it on GPU pods separate from the API, we'd need to re-introduce the topology. Better to keep the door open.
- **Rejected because:** The trade-off changes in Phase 7+; locking in monolith forever is worse.

## Trade-off summary

| Dimension | Embed v1 | Service v1 |
|---|---|---|
| Phase-3 dev velocity | High | Medium |
| Phase-3 portfolio signal | Medium | High |
| Phase-7 portfolio signal | High (extracted with eval data) | Same |
| Deployment complexity | 1 service | 2 services |
| Failure modes | Fewer | More |

## Notes on the design docs

**Partially overrides** ADR-0009 for v1: the retrieval interface is REST-shaped (Pydantic contracts ready) but called in-process. Network-bound REST resumes in Phase 7. The C4 L2 container diagram still shows retrieval as a logical container; the v1 deployment view (added in Phase 7) shows it co-located with the API container until extraction.

## References

- ADR-0009 (REST not gRPC between services)
- `Enterprise_RAG_Folder_Structure.md` `apps/retrieval-service/`
