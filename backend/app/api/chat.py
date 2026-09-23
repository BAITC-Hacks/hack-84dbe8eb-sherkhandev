from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.contracts import ChatRequest, ChatResponse, SessionContext
from app.dependencies import get_agent_service, get_session_context, get_session_lock

router = APIRouter()


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(
    http_request: Request,
    request: ChatRequest,
    context: SessionContext = Depends(get_session_context),
    lock: asyncio.Lock = Depends(get_session_lock),
) -> ChatResponse:
    agent = await get_agent_service(http_request)
    async with lock:
        return await agent.handle_message(context, request)
