"""Error-handler middleware translating DomainError → JSON envelope.

Envelope shape per Enterprise_RAG_Database_Design.md §24:

    {
      "error": {
        "code": "RBAC_DENIED",
        "message": "...",
        "request_id": "req_...",
        "details": {}
      }
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sentinelrag_shared.errors import DomainError, ErrorCode
from sentinelrag_shared.logging import get_logger

from app.db.session import current_request_id

log = get_logger(__name__)


def _envelope(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": current_request_id.get(),
            "details": details or {},
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        log.info(
            "request.domain_error",
            code=str(exc.code),
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(str(exc.code), exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                str(ErrorCode.VALIDATION_FAILED),
                "Request validation failed.",
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Don't leak internal details. Log them; return generic message.
        log.exception("request.unexpected_error", exc_class=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                str(ErrorCode.INTERNAL_ERROR),
                "Internal server error.",
            ),
        )
