"""FastAPI dependencies shared by all routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.contracts import CatalogPort, CartPort, ConditionsPort, SessionContext
from app.sessions import SessionStore


async def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


async def get_session_context(
    authorization: Annotated[str | None, Header()] = None,
    sessions: SessionStore = Depends(get_session_store),
) -> SessionContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "SESSION_INVALID", "message": "Valid bearer session required", "retryable": False})
    token = authorization.removeprefix("Bearer ").strip()
    context = await sessions.authenticate(token)
    if context is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_INVALID", "message": "Valid bearer session required", "retryable": False})
    return context


async def get_session_lock(
    context: SessionContext = Depends(get_session_context),
    sessions: SessionStore = Depends(get_session_store),
):
    lock = await sessions.get_lock(context.session_id)
    if lock is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_INVALID", "message": "Valid session required", "retryable": False})
    return lock


async def _state_service(request: Request, name: str):
    service = getattr(request.app.state, name, None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "SOURCE_UNAVAILABLE", "message": f"Required service is not connected: {name}", "retryable": True},
        )
    return service


async def get_catalog_service(request: Request) -> CatalogPort:
    return await _state_service(request, "catalog")


async def get_cart_service(request: Request) -> CartPort:
    return await _state_service(request, "cart")


async def get_conditions_service(request: Request) -> ConditionsPort:
    return await _state_service(request, "conditions")


async def get_agent_service(request: Request):
    return await _state_service(request, "agent")


__all__ = [
    "get_agent_service",
    "get_catalog_service",
    "get_cart_service",
    "get_conditions_service",
    "get_session_context",
    "get_session_lock",
    "get_session_store",
]
