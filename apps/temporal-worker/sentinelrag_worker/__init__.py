"""SentinelRAG Temporal worker.

Hosts durable workflows + activities for ingestion (Phase 2), evaluation
(Phase 4), and any future batch operation. Per ADR-0007, Temporal replaces
the Celery references in the original folder structure.
"""

__version__ = "0.1.0"
