"""Standard error envelope and exception types.

The error response shape matches Enterprise_RAG_Database_Design.md §24:

    {
      "error": {
        "code": "RBAC_DENIED",
        "message": "...",
        "request_id": "req_abc123",
        "details": {}
      }
    }
"""

from sentinelrag_shared.errors.codes import ErrorCode
from sentinelrag_shared.errors.exceptions import (
    AuthRequiredError,
    BudgetExceededError,
    DomainError,
    NotFoundError,
    RBACDeniedError,
    ValidationFailedError,
)

__all__ = [
    "AuthRequiredError",
    "BudgetExceededError",
    "DomainError",
    "ErrorCode",
    "NotFoundError",
    "RBACDeniedError",
    "ValidationFailedError",
]
