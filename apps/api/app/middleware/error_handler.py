from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    del request
    detail = exc.detail if isinstance(exc.detail, (dict, list, str)) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled application exception", exc_info=exc)
    del request
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
