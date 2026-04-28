"""SentinelRAG ingestion service.

Long-running document parsing + chunking + embedding pipeline. Orchestrated
by Temporal workflows in ``apps/temporal-worker``; this service exposes a
small HTTP surface and a library-style API the workflow activities import.
"""

__version__ = "0.1.0"
