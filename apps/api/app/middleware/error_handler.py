from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "path": str(request.url.path),
        },
    )
