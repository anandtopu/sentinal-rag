"""AuthContext — the authoritative identity object passed through every request.

The auth middleware constructs an ``AuthContext`` after validating the JWT
and resolving the user's permissions from the database. Subsequent layers
(routes, services, repositories) read this instead of touching the JWT.

Note that the JWT's claims are *advisory* for everything except identity.
Permissions in particular are loaded from our DB (see ADR-0008) — Keycloak
roles in the JWT are ignored for authorization decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Resolved identity for the active request."""

    user_id: UUID
    tenant_id: UUID
    email: str
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_permission(self, code: str) -> bool:
        return code in self.permissions

    def require_permission(self, code: str) -> None:
        from sentinelrag_shared.errors import RBACDeniedError  # noqa: PLC0415

        if not self.has_permission(code):
            raise RBACDeniedError(
                f"Missing required permission: {code}",
                details={"required": code},
            )
