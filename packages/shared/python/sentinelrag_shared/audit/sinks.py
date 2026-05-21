"""AuditSink implementations (ADR-0016).

The two production sinks (Postgres + S3 Object Lock) are independent — the
:class:`DualWriteAuditService` orchestrates "synchronous Postgres + async
S3" via these protocol-conforming objects. Tests inject the in-memory
sink from :mod:`sentinelrag_shared.audit.service`.
"""

from __future__ import annotations

import gzip
import json
from typing import TYPE_CHECKING, Protocol

from sentinelrag_shared.audit.event import AuditEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sentinelrag_shared.object_storage import ObjectStorage


class AuditSinkError(Exception):
    """Raised when a sink fails to persist an event.

    The DualWriteAuditService swallows this for *secondary* sinks (so a
    transient S3 failure doesn't block the request); the primary Postgres
    sink lets it propagate so the caller sees the failure.
    """


class AuditSink(Protocol):
    async def write(self, event: AuditEvent) -> None: ...


class PostgresAuditSink:
    """Synchronous Postgres write to ``audit_events``.

    Uses the same session the request runs in so the audit row commits
    atomically with the rest of the request's transaction. RLS on
    ``audit_events`` (migration 0010) enforces tenant isolation — the row
    is rejected if the session's ``app.current_tenant_id`` does not match
    ``event.tenant_id``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(self, event: AuditEvent) -> None:
        from sqlalchemy import (
            text,
        )  # noqa: PLC0415 — keep this module sqla-free at import

        try:
            await self._session.execute(
                text(
                    "INSERT INTO audit_events ("
                    "  id, tenant_id, actor_user_id, event_type, resource_type, "
                    "  resource_id, action, ip_address, user_agent, request_id, "
                    "  before_state, after_state, metadata, created_at"
                    ") VALUES ("
                    "  :id, :tid, :uid, :etype, :rtype, :rid, :act, :ip, :ua, :req, "
                    "  CAST(:before AS jsonb), CAST(:after AS jsonb), "
                    "  CAST(:meta AS jsonb), :ts"
                    ")"
                ),
                {
                    "id": str(event.id),
                    "tid": str(event.tenant_id),
                    "uid": str(event.actor_user_id) if event.actor_user_id else None,
                    "etype": event.event_type,
                    "rtype": event.resource_type,
                    "rid": str(event.resource_id) if event.resource_id else None,
                    "act": event.action,
                    "ip": event.ip_address,
                    "ua": event.user_agent,
                    "req": event.request_id,
                    "before": (
                        json.dumps(event.before_state)
                        if event.before_state is not None
                        else None
                    ),
                    "after": (
                        json.dumps(event.after_state)
                        if event.after_state is not None
                        else None
                    ),
                    "meta": json.dumps(event.metadata),
                    "ts": event.created_at,
                },
            )
        except Exception as exc:
            raise AuditSinkError(f"postgres audit write failed: {exc}") from exc


class ObjectStorageAuditSink:
    """Async write to an immutable bucket (S3/GCS) per ADR-0016.

    Object Lock retention + Compliance mode are configured at bucket
    creation by Terraform; this sink only PUTs the gzipped JSON payload.
    The bucket-level default retention applies to every object so we
    don't pass per-object Object-Lock headers.
    """

    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

    async def write(self, event: AuditEvent) -> None:
        try:
            payload = event.model_dump_json().encode("utf-8")
            body = gzip.compress(payload)
            await self._storage.put(
                key=event.s3_key(),
                data=body,
                content_type="application/gzip",
                custom_metadata={
                    "event-type": event.event_type,
                    "tenant-id": str(event.tenant_id),
                },
            )
        except Exception as exc:
            raise AuditSinkError(f"object-storage audit write failed: {exc}") from exc
