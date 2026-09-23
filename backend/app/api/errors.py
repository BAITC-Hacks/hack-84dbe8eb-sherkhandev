from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent import AgentError


def error_payload(code: str, message: str, retryable: bool) -> dict[str, dict[str, Any]]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            str(detail.get("code", "INTERNAL_ERROR")),
            str(detail.get("message", "Request failed")),
            bool(detail.get("retryable", False)),
        ),
    )


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=error_payload("INVALID_REQUEST", "Request validation failed", False))


async def agent_exception_handler(_: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.retryable),
    )


async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=error_payload("INTERNAL_ERROR", "Internal server error", False))
