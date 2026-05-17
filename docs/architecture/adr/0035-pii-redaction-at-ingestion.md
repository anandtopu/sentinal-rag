# ADR-0035: PII redaction at ingestion

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** privacy, ingestion, compliance, pii

## Context

Multi-tenant RAG ingests arbitrary documents. Customer policy (HIPAA,
SOC2 CC6.7, GDPR Art. 5(1)(c)) routinely requires that PII not appear
in derived artifacts that are queried, embedded, or sent to a
third-party LLM. The relevant SentinelRAG surfaces:

- `document_chunks.content` — used by retrieval *and* spliced into
  the LLM prompt as "context."
- `chunk_embeddings.*` — derived vectors. Embeddings of PII strings
  can leak the underlying value via nearest-neighbor inversion at
  scale; the practical threat is small but the compliance posture
  expects we treat embeddings as derived PII.
- LLM-bound prompts — for cloud generators (OpenAI, Anthropic) the
  PII would leave the tenant's control entirely.
- Audit trail and logs — already addressed by [ADR-0016](0016-immutable-audit-dual-write.md)
  + [ADR-0032](0032-right-to-be-forgotten.md).

The 2026-05-16 architecture review flagged this as a missing ADR.
The PRD § 7 lists "PII redaction" as a v1 expectation but doesn't
commit to a library or pipeline placement.

Constraints:

- Ingestion is a [Temporal](0007-temporal-over-celery.md) workflow.
  Activities are idempotent; adding a redaction step doesn't break
  the replay model.
- The original document copy is stored in object storage per
  [ADR-0015](0015-raw-text-in-object-storage.md). Customer
  compliance + GDPR-controller-role obligations frequently demand
  we keep the *original* available for legal review even when
  derived artifacts redact it.
- Some tenants don't want redaction at all (technical documentation
  with email addresses for support; security docs with example
  IPs). The feature must be opt-in per tenant.
- The redactor must run **before** chunking + embedding so the
  vectors never include PII.

## Decision

Adopt **Microsoft Presidio (rule-based, opt-in per tenant) as the
redaction engine, applied between document parsing and chunking in
the Temporal ingestion workflow. The object-storage source copy is
kept original; only `document_chunks.content` (and the embeddings
derived from it) are redacted.**

### Pipeline placement

```
Parse (unstructured) → Redact (Presidio, optional) → Chunk → Embed → Persist
                              ▲
                              │
                          Per-tenant flag via Unleash (ADR-0018)
```

The redactor is a new Temporal activity inserted between the existing
parse and chunk activities. The activity:

1. Reads the tenant's `pii_redaction.enabled` flag via the existing
   `FeatureFlagClient` adapter (ADR-0018 + R2's
   `sentinelrag_shared.feature_flags`).
2. If disabled, passes the parsed text through unchanged.
3. If enabled, runs Presidio's `AnalyzerEngine` with the configured
   recognizers, then `AnonymizerEngine` to replace each detected span
   with a category placeholder (`[REDACTED:EMAIL]`, `[REDACTED:PHONE]`,
   `[REDACTED:SSN]`, etc.).
4. Emits a structured-log entry with detection counts per category
   (no actual PII strings logged).
5. Records the redaction event on the document version row's metadata
   so the trace UI can surface "this document was ingested with PII
   redaction (v1)".

### Recognizer set

The default recognizer set covers the categories listed in
Presidio's `pii_entities` table that overlap with common compliance
requirements:

- `EMAIL_ADDRESS`
- `PHONE_NUMBER`
- `US_SSN`, `US_PASSPORT`, `US_DRIVER_LICENSE`
- `CREDIT_CARD`
- `IBAN_CODE`
- `IP_ADDRESS` (configurable — false-positive risk on technical docs)
- `PERSON` (NER-driven; configurable)
- `DATE_TIME` is explicitly excluded by default — too lossy for
  factual documents.

Tenants can override the recognizer list via a JSON column on
`tenants.pii_policy` (added in the implementation phase).

### Source-doc copy in object storage stays original

The bucket is versioned per [ADR-0015](0015-raw-text-in-object-storage.md);
the original is what the compliance-evidence team reads. RTBF
([ADR-0032](0032-right-to-be-forgotten.md)) handles the case where
the original itself must be purged.

### Audit-prompt redaction

The audit-trail prompt-text capture under
`include_debug_trace` (ADR-0034) records the *redacted* chunks
because that's what the model saw. The original document content is
not re-attached to the audit row.

### Performance + memory

Presidio's default English model is ~250MB on disk; loading takes
~3–5s on cold start. The ingestion-service is a long-running worker
(Temporal activities), so the load cost is paid once per worker pod
boot. Per-document latency is dominated by `unstructured` parsing
already; the redactor adds 30–80ms per 1k tokens in our smoke
measurements (revisit when R5 implementation lands).

### What about per-query / hot-path redaction?

The cascade in ADR-0034 considers *adversarial* content in the
context. PII redaction at ingestion is the opposite story — we
clean derived content *once*, at write-time, and never touch the
query path. A per-query redactor would double-redact (chunks are
already redacted) and add hot-path latency for no gain.

## Consequences

### Positive

- The compliance story is concrete: the derived corpus and its
  embeddings carry no PII for opt-in tenants. The original is
  available for legal review per ADR-0015.
- Presidio is mature, MIT-licensed, and ships with extensible
  recognizers — adding a tenant-specific entity (employee badge
  number patterns, customer order ID formats) is a 10-line custom
  recognizer, no fork.
- Per-tenant opt-in via Unleash means customers who NEED redaction
  get it; customers who don't (technical docs) keep the higher-
  fidelity corpus.
- No hot-path latency penalty. The cost lives in the ingestion
  workflow, which runs out of the request path.

### Negative

- Presidio is rule-based + NER-assisted. False positives on
  domain-specific text are real (a SKU like `123-45-6789` matches
  SSN format). The tenant policy override is the escape valve;
  documented in the runbook.
- The opposite — false negatives on novel PII patterns — is also
  real. We don't claim "all PII redacted forever"; the ADR claims
  "the documented entity categories at Presidio's published
  recognizer precision."
- A new ML model gets loaded into the ingestion pod. Adds memory
  pressure on the ingestion-service worker pods (~250MB).
- One more thing for the implementation phase to maintain. The
  ingestion test suite must include a redaction-correctness corpus.

### Neutral

- The decision is reversible per tenant via the Unleash flag —
  ingesting a document with redaction off, then later flipping the
  flag on, would require a re-ingestion pass for that document.
  Documented in the runbook; not automated in v1.

## Alternatives considered

### Option A — Microsoft Presidio (this)
- See above.

### Option B — Rule-based regex library (e.g. `scrubadub`)
- **Pros:** Lighter dependency; no NER model.
- **Cons:** No NER means person-name detection is brittle; less
  community momentum than Presidio.
- **Rejected because:** Presidio's NER recall on `PERSON` is the
  killer feature; regex-only impl is worse on the same categories.

### Option C — Commercial PII service (Skyflow, Nightfall)
- **Pros:** SaaS = no model hosting; usually better recall.
- **Cons:** Cost; data leaves the tenant boundary on the way to the
  vendor; contradicts the "self-hosted by default" posture from
  [ADR-0014](0014-hybrid-llm-strategy.md).
- **Rejected because:** the self-hosted posture is the differentiator
  for the platform.

### Option D — No redaction; tell tenants to redact upstream
- **Pros:** Zero implementation work.
- **Cons:** Loses customers in regulated verticals; doesn't satisfy
  PRD § 7.
- **Rejected because:** explicit PRD commitment.

### Option E — Encrypt PII in `document_chunks.content` with a tenant key
- **Pros:** Round-tripable; original text recoverable for audit.
- **Cons:** Encrypted text can't be embedded — the whole RAG flow
  breaks. You'd need to embed plaintext, then encrypt; the embedding
  vectors still carry the leakage path.
- **Rejected because:** breaks the embedding step.

## Trade-off summary

| Dimension | Presidio (this) | Scrubadub | Commercial PII | No redaction |
|---|---|---|---|---|
| Coverage breadth | High (entity categories) | Medium | High | None |
| `PERSON` recall | High (NER) | Low | High | N/A |
| Self-hosted | Yes | Yes | No | N/A |
| Per-tenant tuneable | Yes (custom recognizers) | Yes | Limited | N/A |
| Memory footprint | ~250MB | Tiny | 0 | 0 |
| Customer policy match | Most | Some | Most | Few |
| Implementation effort | Medium | Low | Low (integration only) | None |

## Notes on the design docs

PRD § 7 lists "PII redaction" without specifying. This ADR commits
to Presidio.

`Enterprise_RAG_Folder_Structure.md` has
`apps/ingestion-service/sentinelrag_ingestion_service/`; the
redactor activity lands there as a new module
(`activities/redact.py`) when the implementation phase ships.

The `tenants` table will gain a `pii_policy JSONB` column to carry
the per-tenant recognizer override list — that's a class-A
expand-class migration per [ADR-0033](0033-zero-downtime-schema-migrations.md).

## References

- [ADR-0007](0007-temporal-over-celery.md) — ingestion runs on
  Temporal; this ADR adds an activity
- [ADR-0013](0013-unstructured-parsing.md) — document parsing
  upstream of the redactor
- [ADR-0015](0015-raw-text-in-object-storage.md) — source copy stays
  original
- [ADR-0018](0018-feature-flags-unleash.md) — per-tenant opt-in
- [ADR-0032](0032-right-to-be-forgotten.md) — companion privacy ADR
  for delete-on-request
- [ADR-0034](0034-prompt-injection-defense.md) — companion ADR for
  adversarial content (different threat model)
- [Microsoft Presidio](https://microsoft.github.io/presidio/) — the
  chosen library
