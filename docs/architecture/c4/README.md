# C4 diagrams

C4 model diagrams for SentinelRAG, written in Mermaid so GitHub renders them natively in PRs and the file viewer. Each diagram corresponds to one zoom level of the [C4 model](https://c4model.com/):

| Level | File | What it shows |
|---|---|---|
| L1 — System Context | [`L1-system-context.md`](L1-system-context.md) | SentinelRAG as a single box; the people and external systems it interacts with. |
| L2 — Container | [`L2-container.md`](L2-container.md) | The deployable units (api, temporal-worker, frontend, data plane, identity, observability) and the protocols between them. |
| L3 — Component | [`L3-component-rag-core.md`](L3-component-rag-core.md) | A zoom into the RAG core — orchestrator, retrievers, reranker, prompt service, cost gate, audit, generator. |
| L4 — Deployment | [`L4-deployment-aws.md`](L4-deployment-aws.md) | How the L2 containers map onto a real EKS cluster + AWS managed services. GCP mirror is in [`L4-deployment-gcp.md`](L4-deployment-gcp.md). |

## Why Mermaid, not PNG / Structurizr

- GitHub renders Mermaid C4 in `.md` files — diagrams are part of the diff, change reviewable.
- No build step; no asset pipeline; no PNG cache to keep in sync with the YAML.
- Source-of-truth lives next to the ADRs.

The trade-off is a slightly less polished visual than a Structurizr DSL render. Acceptable for this scope — recorded in ADR-0029.

## When to update

| Trigger | Update |
|---|---|
| New deployable container (e.g. dedicated retrieval service) | L2 + L4 |
| New external dependency (new LLM provider, new IDP) | L1 + L2 |
| New component inside the RAG core (e.g. query classifier) | L3 |
| New cloud added or topology shift | L4 (per cloud) |

If you're adding a new ADR, link it from the relevant diagram's "Related ADRs" section so readers can jump from the picture to the rationale.
