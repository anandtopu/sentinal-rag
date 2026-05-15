"""Domain exception hierarchy.

Routes raise these; an error-handling middleware translates them into the
standard JSON envelope with the right HTTP status. This decouples business
logic from FastAPI's HTTPException machinery.
"""

from __future__ import annotations

from typing import Any

from sentinelrag_shared.errors.codes import ErrorCode


class DomainError(Exception):
    """Base class for application-defined errors."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500
    default_message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details or {}


class AuthRequiredError(DomainError):
    code = ErrorCode.AUTH_REQUIRED
    http_status = 401
    default_message = "Authentication required."


class AuthInvalidError(DomainError):
    code = ErrorCode.AUTH_INVALID
    http_status = 401
    default_message = "Invalid or expired credentials."


class RBACDeniedError(DomainError):
    code = ErrorCode.RBAC_DENIED
    http_status = 403
    default_message = "You do not have permission to perform this action."


class NotFoundError(DomainError):
    code = ErrorCode.TENANT_NOT_FOUND  # subclasses override
    http_status = 404
    default_message = "Resource not found."


class TenantNotFoundError(NotFoundError):
    code = ErrorCode.TENANT_NOT_FOUND
    default_message = "Tenant not found."


class UserNotFoundError(NotFoundError):
    code = ErrorCode.USER_NOT_FOUND
    default_message = "User not found."


class RoleNotFoundError(NotFoundError):
    code = ErrorCode.ROLE_NOT_FOUND
    default_message = "Role not found."


class ValidationFailedError(DomainError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = 422
    default_message = "Validation failed."


class ConflictError(DomainError):
    code = ErrorCode.CONFLICT
    http_status = 409
    default_message = "Resource state conflict."


class BudgetExceededError(DomainError):
    """Hard cap reached — request rejected (ADR-0022)."""

    code = ErrorCode.BUDGET_EXCEEDED
    http_status = 402
    default_message = "Tenant budget exceeded for the active period."


class TemporalUnavailableError(DomainError):
    """Temporal is required for durable async work but is not reachable."""

    code = ErrorCode.TEMPORAL_UNAVAILABLE
    http_status = 503
    default_message = "Temporal is unavailable."
