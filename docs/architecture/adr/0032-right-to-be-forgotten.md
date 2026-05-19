# ADR-0032: Right-to-be-forgotten vs. immutable audit

- **Status:** Accepted
- **Date:** 2026-05-17
- **Tags:** compliance, privacy, audit, gdpr, ccpa

## Context

Two pillars from earlier ADRs collide:

1. **[ADR-0016](0016-immutable-audit-dual-write.md):** every audit
   event is append-only at the application layer and mirrored to S3
   under Object Lock COMPLIANCE retention. The point is that no actor
   inside the system — including a tenant admin or a SentinelRAG
   operator — can remove or alter a recorded action.
2. **GDPR Art. 17 / CCPA §1798.105** give a data subject the right to
   request erasure of their personal data. Multi-tenant SaaS that
   processes user-attributable data on behalf of customers needs an
   implementable answer to "delete me."

The 2026-05-16 architecture review (finding catalog in
[`reviews/2026-05-16-architect-review.md`](../reviews/2026-05-16-architect-review.md))
flagged this as the highest-leverage gap in the ADR backlog. The R5.S1
decisions log entry locked the direction in advance of writing this
ADR; the body below captures the *why*.

The constraints we have to honor:

- Object Lock on the S3 mirror is non-negotiable; the legal posture is
  that the audit trail is not under SentinelRAG's discretion to
  remove. That bucket survives the retention window.
- The Postgres `audit_events` table is append-only at the app level
  but has no DB-side write protection — it could be `DELETE`d by
  someone with raw DB access. The mirror is what guarantees survival.
- Personally identifiable surfaces in SentinelRAG today are:
  document content + chunk embeddings, query text, generated answers,
  audit-event metadata (actor_user_id, request_id, IP if logged),
  usage_records (actor_user_id), and the user/tenant rows themselves.

## Decision

**Support RTBF**, by separating *deletable user content* from
*pseudonymous audit metadata*. The audit trail survives forever in
S3 Object Lock; what it points at no longer resolves to a person.

### Deletable surfaces (per-user RTBF)

When `POST /admin/rtbf` is invoked with a target `user_id`, the
following are purged or redacted:

| Surface | Operation |
|---|---|
| `document_chunks.content` (rows authored by the user) | `UPDATE content = '[RTBF redacted]'` |
| `chunk_embeddings.*` (rows for the above chunks) | `DELETE` |
| Source-doc copies in object storage (per-user prefix) | versioned bucket — delete *all versions* of each key |
| `query_sessions.query_text` (rows where `user_id = $1`) | `UPDATE query_text = '[RTBF redacted]'` |
| `generated_answers.answer_text` (joined via `query_session_id`) | `UPDATE answer_text = '[RTBF redacted]'` |
| `answer_citations.quoted_text` (joined via `generated_answer_id`) | `UPDATE quoted_text = NULL` |

The reranker / NLI / judge verdict columns (`grounding_score`,
`nli_verdict`, `judge_verdict`, etc.) are *not* PII and stay so the
post-RTBF rows still describe the system's behavior at the time, just
without the contents that produced it.

### Audit retention (pseudonymous)

`audit_events` rows are **preserved**. The Object Lock COMPLIANCE
retention window on the S3 mirror enforces this regardless of any
DB-side action.

Direct PII (actor email, IP) is held *indirectly*. Today `audit_events`
references `actor_user_id` directly; this ADR introduces a tombstone
mapping:

```
user_identity_map
    pseudonym_id   UUID    PK
    user_id        UUID    NULL                 -- nulled on RTBF
    tenant_id      UUID    NOT NULL             -- needed for RLS join post-RTBF
    created_at     TIMESTAMPTZ
```

- Every `users` row gets a paired `user_identity_map` row at signup.
- Foreign keys that today reference `users.id` (audit, usage, sessions,
  generated answers) are migrated to reference `user_identity_map.pseudonym_id`
  in a follow-on migration.
- On per-user RTBF the workflow runs `UPDATE user_identity_map SET user_id = NULL WHERE pseudonym_id = ...`.
  The pseudonym still joins historical rows; the link to a person is
  gone.

Email in `users.email` is hashed-and-cleared during RTBF (replace with
a deterministic hash for deduplication, drop the cleartext).

### Tenant-level RTBF

"Forget this tenant entirely" is a separate workflow with the same
shape — chunks + embeddings + docs purged; the tenant row tombstoned
via a similar `tenant_identity_map`. The S3 audit prefix survives the
Object Lock retention window then ages out per the bucket's lifecycle
policy.

### Operational shape

- **Temporal:** `RtbfWorkflow` with idempotent activities. Two
  variants: per-user and per-tenant. Idempotent because RTBF is
  potentially run repeatedly under retry — the second run must be a
  no-op, not a double-redact-of-already-redacted-rows.
- **Route:** `POST /admin/rtbf` accepts `{target_type, target_id}`,
  starts the workflow, returns the workflow id for status polling.
- **Permission:** new `rtbf:execute` permission. Gated behind a
  platform-admin role; not exposed to tenant admins by default
  (some plans may delegate this — flag-gated, deferred ADR).
- **Audit emission:** the workflow itself emits a `rtbf.completed`
  audit event keyed by the *pseudonym*, so the action is auditable
  without re-identifying the subject. The Object Lock mirror retains
  this row alongside the now-pseudonymous trail.

### Restoration

RTBF is irreversible. Once `user_id` is NULL'd, the mapping is gone;
the pseudonym cannot be re-linked. Document this explicitly in the
admin runbook + the API response body.

## Consequences

### Positive

- Compliant with GDPR Art. 17 + CCPA §1798.105 for the common
  interpretation — personally identifiable data is gone, even though
  some derived signals (verdicts, latencies, costs) survive in
  pseudonymous form.
- The audit trail's integrity guarantee from ADR-0016 is preserved.
  Object Lock COMPLIANCE retention is not violated; pseudonymized
  rows are still mathematically the same rows.
- The `user_identity_map` indirection is a small migration once
  (R5.S2 will discuss how to roll it out without downtime). After
  that the pattern composes with every future identity-bearing
  table.
- Tenant RTBF is feasible without operator coordination with the
  S3 retention policy — chunks + embeddings + docs disappear; the
  audit prefix simply ages out.

### Negative

- The "no trace at all" reading of GDPR — favored by some EU DPAs —
  is *not* satisfied. SentinelRAG retains pseudonymous audit rows
  that, given access to the S3 mirror, name a specific tenant +
  pseudonym + action. The ADR documents this trade-off explicitly.
  The controller-vs-processor framing (see References) justifies
  it: SentinelRAG-as-processor cannot unilaterally delete records
  that its controllers (tenant operators) may be legally required
  to keep for compliance evidence.
- The tombstone mapping adds a join to every audit query that wants
  to display a user identifier. Most audit dashboards display the
  pseudonym directly — no join needed.
- RTBF must be run *before* the S3 retention window expires on any
  audit row that mentions the user. We accept that an
  RTBF-after-retention rerun is a no-op for that row.

### Neutral

- The redaction strings (`[RTBF redacted]`) are uniform across the
  codebase to keep the audit trail descriptive. We do not blank to
  empty string — that would lose the "this was redacted" signal.

## Alternatives considered

### Option A — Drop the audit row entirely on RTBF
- **Pros:** Strictest GDPR reading; nothing about the user survives.
- **Cons:** Breaks ADR-0016 (audit immutability) and the Object Lock
  retention contract. Object Lock is a regulatory commitment;
  violating it is itself a compliance incident.
- **Rejected because:** The Object Lock posture isn't a SentinelRAG
  technical choice — it's the legal framing under which we offer
  the audit trail at all. Customers who need that trail for SOC2 /
  ISO27001 cannot have it conditional on subsequent RTBF requests.

### Option B — Keep `actor_user_id` directly; redact email only
- **Pros:** Simpler migration; no tombstone table.
- **Cons:** Re-identification trivial — `audit_events JOIN users`
  recovers the user even after the email row is gone, if the
  `users.id` value is still recoverable from anywhere (it usually
  is, via FK ON DELETE constraints).
- **Rejected because:** Re-identification risk; the tombstone
  pattern is small and well-understood.

### Option C — Encrypt user-identifying audit columns; rotate the key on RTBF
- **Pros:** Cryptographic deniability; the row survives in
  ciphertext.
- **Cons:** Per-user keys are a key-management nightmare; per-tenant
  keys give you the same auditability concern as Option B on a
  larger blast radius. The S3 Object Lock copy can't be re-encrypted
  in place during the retention window.
- **Rejected because:** Operational cost outsizes the benefit over
  the chosen pseudonymization model.

## Trade-off summary

| Dimension | Tombstone (this) | Drop audit row | Encrypt + rotate |
|---|---|---|---|
| ADR-0016 compliance | Preserved | Broken | Preserved (mostly) |
| GDPR Art. 17 satisfied | Yes (controller framing) | Yes (strictest) | Yes |
| Re-identification risk | Low | None | Low |
| Operational complexity | One small migration | Per-RTBF audit deletes | Per-user key rotation + S3 reencrypt |
| Forward audit completeness | Full | Partial (gaps after RTBF) | Full |
| Implementation effort | Bounded (1 migration + 1 workflow) | Bounded | High (KMS + S3 reencrypt) |

## Notes on the design docs

This ADR adds a NEW concern not present in `Enterprise_RAG_PRD.md` or
the Database Design doc. The follow-on Alembic migration (post-R5
implementation phase) introduces `user_identity_map` and
`tenant_identity_map`, then ports the FKs over. The new admin route
+ Temporal workflow land in their own implementation ADR / PR per the
project convention (no code in ADR PRs).

`Enterprise_RAG_Deployment.md` § "Compliance & data retention" should
be updated when the implementation lands so the deploy runbook covers
the S3 lifecycle policy that the audit-prefix relies on (Object Lock
COMPLIANCE + a documented retention horizon).

## References

- [ADR-0016](0016-immutable-audit-dual-write.md) — audit immutability,
  the constraint this ADR reconciles with
- [ADR-0015](0015-raw-text-in-object-storage.md) — source-doc copies
  in object storage (versioned bucket = purge all versions on RTBF)
- [GDPR Art. 17](https://gdpr-info.eu/art-17-gdpr/) — Right to
  erasure
- [CCPA §1798.105](https://oag.ca.gov/privacy/ccpa) — Consumer's
  right to delete personal information
- [EDPB guidance on controllers vs processors](https://edpb.europa.eu/system/files/2021-07/eppb_guidelines_202007_controllerprocessor_final_en.pdf)
  — the framing this ADR uses to keep pseudonymous audit rows
