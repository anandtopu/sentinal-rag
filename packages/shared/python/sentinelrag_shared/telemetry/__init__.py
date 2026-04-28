"""OpenTelemetry bootstrap for SentinelRAG services.

Single entry point: :func:`configure_telemetry`. Call once at process startup,
typically before instantiating the FastAPI app.
"""

from sentinelrag_shared.telemetry.meters import (
    record_budget_decision,
    record_grounding,
    record_llm_cost,
    record_query_completed,
    record_stage_latency,
)
from sentinelrag_shared.telemetry.setup import configure_telemetry

__all__ = [
    "configure_telemetry",
    "record_budget_decision",
    "record_grounding",
    "record_llm_cost",
    "record_query_completed",
    "record_stage_latency",
]
