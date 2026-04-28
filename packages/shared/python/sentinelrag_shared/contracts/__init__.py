"""Cross-service Pydantic contracts.

Models in this package are imported by both the producer and the consumer of
a service-to-service or workflow-to-activity message. Adding a field requires
coordinating both sides; renaming requires a versioned migration.

Conventions:
    - All models inherit from a base ``Contract`` that pins the Pydantic config.
    - Workflow inputs are immutable (``frozen=True``) — Temporal replays them
      from history and we want to detect accidental mutation.
    - UUIDs are typed as ``UUID``; serialized as strings; deserialized via
      Pydantic's standard parsing.
"""

from sentinelrag_shared.contracts.base import Contract
from sentinelrag_shared.contracts.evaluation import (
    EvaluationRunWorkflowInput,
    EvaluationRunWorkflowResult,
)
from sentinelrag_shared.contracts.ingestion import (
    IngestionWorkflowInput,
    IngestionWorkflowResult,
)

__all__ = [
    "Contract",
    "EvaluationRunWorkflowInput",
    "EvaluationRunWorkflowResult",
    "IngestionWorkflowInput",
    "IngestionWorkflowResult",
]
