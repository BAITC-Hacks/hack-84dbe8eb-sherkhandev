from fastapi import APIRouter, Request

from app.contracts import SessionCreated
from app.dependencies import get_session_store

router = APIRouter()


@router.post("/api/v1/sessions", response_model=SessionCreated, status_code=201)
async def create_session(request: Request) -> SessionCreated:
    sessions = await get_session_store(request)
    return await sessions.create()
