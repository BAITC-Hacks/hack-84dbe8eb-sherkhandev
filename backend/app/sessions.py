"""In-memory authenticated sessions and per-session serialization."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any

from app.contracts import SessionContext, SessionCreated


@dataclass(slots=True)
class SessionState:
    context: SessionContext
    token_hash: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    history: list[dict[str, Any]] = field(default_factory=list)
    selected_warehouse_id: str | None = None
    selected_product_id: str | None = None


class SessionStore:
    """Stores only token hashes; clients receive the clear token once."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._by_token_hash: dict[str, str] = {}
        self._guard = asyncio.Lock()

    async def create(self) -> SessionCreated:
        async with self._guard:
            session_id = secrets.token_urlsafe(18)
            session_token = secrets.token_urlsafe(32)
            token_hash = self._hash(session_token)
            state = SessionState(
                context=SessionContext(session_id=session_id),
                token_hash=token_hash,
            )
            self._sessions[session_id] = state
            self._by_token_hash[token_hash] = session_id
            return SessionCreated(session_id=session_id, session_token=session_token)

    async def authenticate(self, session_token: str) -> SessionContext | None:
        if not session_token:
            return None
        token_hash = self._hash(session_token)
        async with self._guard:
            session_id = self._by_token_hash.get(token_hash)
            if session_id is None:
                return None
            state = self._sessions.get(session_id)
            if state is None or not secrets.compare_digest(state.token_hash, token_hash):
                return None
            return state.context

    async def get_lock(self, session_id: str) -> asyncio.Lock | None:
        async with self._guard:
            state = self._sessions.get(session_id)
            return state.lock if state else None

    async def get_state(self, session_id: str) -> SessionState | None:
        async with self._guard:
            return self._sessions.get(session_id)

    async def append_history(self, session_id: str, role: str, content: Any) -> None:
        state = await self.get_state(session_id)
        if state is None:
            return
        state.history.append({"role": role, "content": content})

    async def history_tail(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        state = await self.get_state(session_id)
        if state is None:
            return []
        return list(state.history[-limit:])

    async def set_selection(
        self,
        session_id: str,
        *,
        warehouse_id: str | None = None,
        product_id: str | None = None,
    ) -> None:
        state = await self.get_state(session_id)
        if state is None:
            return
        if warehouse_id is not None:
            state.selected_warehouse_id = warehouse_id
        if product_id is not None:
            state.selected_product_id = product_id

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

