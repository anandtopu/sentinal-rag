"""Application-level OpenTelemetry meters (ADR-0023 / Phase 6).

The OTel SDK is configured by :func:`configure_telemetry`; this module
defines the named instruments services emit during request handling.
Instruments are lazy-initialized on first access so importing the module
in a process that hasn't called ``configure_telemetry`` is safe.

Cardinality discipline: we keep tenant_id off attribute keys for high-volume
counters (per-tenant counts blow up Prometheus storage at scale). The cost
gauge does carry tenant_id because budget alerts need it; rare events can
afford the cardinality.
"""

from __future__ import annotations

from functools import lru_cache

from opentelemetry import metrics

_METER_NAME = "sentinelrag.app"


@lru_cache(maxsize=1)
def _meter() -> metrics.Meter:
    return metrics.get_meter(_METER_NAME)


# Counters --------------------------------------------------------------------

@lru_cache(maxsize=1)
def queries_total() -> metrics.Counter:
    """Number of /query calls. Attributes: ``status`` (completed|abstained|failed)."""
    return _meter().create_counter(
        "sentinelrag_queries_total",
        unit="1",
        description="Total queries executed by the orchestrator",
    )


@lru_cache(maxsize=1)
def budget_decisions_total() -> metrics.Counter:
    """Budget gate decisions. Attributes: ``action`` (allow|downgrade|deny)."""
    return _meter().create_counter(
        "sentinelrag_budget_decisions_total",
        unit="1",
        description="Cost-budget gate decisions (ADR-0022)",
    )


@lru_cache(maxsize=1)
def llm_cost_usd_total() -> metrics.Counter:
    """LLM completion cost in USD. Attributes: ``provider`` (openai|anthropic|ollama)."""
    return _meter().create_counter(
        "sentinelrag_llm_cost_usd_total",
        unit="USD",
        description="LLM completion cost; sums to a per-period spend gauge",
    )


@lru_cache(maxsize=1)
def audit_secondary_failures_total() -> metrics.Counter:
    """Secondary-sink failures inside the dual-write path.

    Attributes: ``sink`` (sink class name, e.g. ``ObjectStorageAuditSink``).
    Used by the audit-drift alarm; the daily reconciliation Schedule
    backfills any missed rows so this counter is an early-warning signal
    rather than a data-loss alarm.
    """
    return _meter().create_counter(
        "sentinelrag_audit_secondary_failures_total",
        unit="1",
        description="Audit dual-write secondary-sink failures (ADR-0016)",
    )


@lru_cache(maxsize=1)
def audit_reconciliation_drift() -> metrics.Counter:
    """Audit drift counts per reconciliation run.

    Attributes: ``side`` (missing_in_s3|missing_in_pg|backfilled). Tenant_id is
    intentionally NOT an attribute — drift is a cross-tenant alarm signal and
    per-tenant cardinality on a counter that fires daily would explode at scale.
    Per-tenant detail lives in the workflow result and the structured log line.
    """
    return _meter().create_counter(
        "sentinelrag_audit_reconciliation_drift",
        unit="1",
        description="Audit events present in one store but not the other (Phase 6.5)",
    )


# Histograms ------------------------------------------------------------------

@lru_cache(maxsize=1)
def stage_latency_ms() -> metrics.Histogram:
    """Per-stage latency. ``stage`` ∈ {bm25, vector, hybrid_merge, rerank, generation, total}."""
    return _meter().create_histogram(
        "sentinelrag_stage_latency_ms",
        unit="ms",
        description="Latency per pipeline stage",
    )


@lru_cache(maxsize=1)
def grounding_score() -> metrics.Histogram:
    """Token-overlap grounding score (Phase 4 layered detector replaces this)."""
    return _meter().create_histogram(
        "sentinelrag_grounding_score",
        unit="1",
        description="Cheap grounding signal in [0,1] for the produced answer",
    )


@lru_cache(maxsize=1)
def hallucination_layer_latency_ms() -> metrics.Histogram:
    """Per-layer latency for the hallucination cascade (ADR-0010).

    Attributes: ``layer`` (``overlap``|``nli``|``judge``). No tenant_id —
    keeping cardinality bounded so Prometheus storage doesn't blow up
    when the cascade fans out across tens of thousands of tenants.
    """
    return _meter().create_histogram(
        "sentinelrag_hallucination_layer_latency_ms",
        unit="ms",
        description="Latency per layer of the hallucination cascade",
    )


# Helpers ---------------------------------------------------------------------

def record_query_completed(*, status: str, latency_ms: int) -> None:
    """One-shot helper for the orchestrator's terminal-state emission."""
    queries_total().add(1, {"status": status})
    stage_latency_ms().record(latency_ms, {"stage": "total"})


def record_stage_latency(*, stage: str, latency_ms: int) -> None:
    stage_latency_ms().record(latency_ms, {"stage": stage})


def record_budget_decision(*, action: str) -> None:
    budget_decisions_total().add(1, {"action": action})


def record_llm_cost(*, provider: str, cost_usd: float) -> None:
    if cost_usd <= 0:
        return
    llm_cost_usd_total().add(cost_usd, {"provider": provider})


def record_grounding(score: float) -> None:
    if score is None:  # type: ignore[truthy-bool]
        return
    grounding_score().record(score)


def record_audit_drift(*, side: str, count: int) -> None:
    """``side`` ∈ {missing_in_s3, missing_in_pg, backfilled}."""
    if count <= 0:
        return
    audit_reconciliation_drift().add(count, {"side": side})


def record_audit_secondary_failure(*, sink: str) -> None:
    """Increment when a dual-write secondary sink fails. ``sink`` = class name."""
    audit_secondary_failures_total().add(1, {"sink": sink})


def record_hallucination_layer_latency(*, layer: str, latency_ms: int) -> None:
    """``layer`` ∈ {overlap, nli, judge}. Negative latencies are dropped."""
    if latency_ms < 0:
        return
    hallucination_layer_latency_ms().record(latency_ms, {"layer": layer})
