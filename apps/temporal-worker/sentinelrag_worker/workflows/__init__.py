"""Temporal workflow definitions.

Workflows are PURE — no I/O, no randomness, no clock access except via
``workflow.now()`` / ``workflow.uuid4()``. All side effects happen in
activities.

Cross-service input/output models live in
``sentinelrag_shared.contracts``; importing them from here is a convenience
re-export.
"""

from sentinelrag_shared.contracts import IngestionWorkflowInput

from sentinelrag_worker.workflows.ingestion import IngestionWorkflow

__all__ = ["IngestionWorkflow", "IngestionWorkflowInput"]
