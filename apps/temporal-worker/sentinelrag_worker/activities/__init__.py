"""Temporal activities — the I/O-doing functions called by workflows.

Activities can do anything: DB queries, network calls, blocking work.
Temporal handles retries, deadlines, and durability. Each activity below
is idempotent given its keys.
"""

from sentinelrag_worker.activities import ingestion

__all__ = ["ingestion"]
