from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.contracts import ConfirmResult, Cart, SessionContext
from app.dependencies import get_cart_service, get_session_context, get_session_lock

router = APIRouter()


def _raise(result):
    if result.ok:
        return
    code = result.error.code
    status = 404 if code == "ACTION_NOT_FOUND" else 409 if code not in {"SOURCE_UNAVAILABLE"} else 503
    raise HTTPException(status_code=status, detail=result.error.model_dump())


@router.post("/api/v1/cart/actions/{action_id}/confirm", response_model=ConfirmResult)
async def confirm(action_id: str, context: SessionContext = Depends(get_session_context), lock: asyncio.Lock = Depends(get_session_lock), cart=Depends(get_cart_service)):
    async with lock:
        result = await cart.confirm_action(context, action_id)
    _raise(result)
    return result.data


@router.get("/api/v1/cart", response_model=Cart)
async def get_cart(context: SessionContext = Depends(get_session_context), cart=Depends(get_cart_service)):
    result = await cart.get_cart(context); _raise(result); return result.data


@router.get("/cart/view/{view_token}", response_class=HTMLResponse, include_in_schema=False)
async def view_cart(view_token: str, cart=Depends(get_cart_service)):
    status, body = await cart.render_view(view_token)
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

