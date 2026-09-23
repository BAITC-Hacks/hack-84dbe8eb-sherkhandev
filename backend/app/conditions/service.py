"""Read-only, mode-isolated conditions provider."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.contracts import ConditionsResult, ErrorInfo, ToolResult


class ConditionsService:
    topics = {"payment", "delivery", "minimum_order"}

    def __init__(self, data_path: str | Path, mode: str) -> None:
        self.data_path = Path(data_path)
        self.mode = mode
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def get_conditions(self, topic: str) -> ToolResult[ConditionsResult]:
        if topic not in self.topics:
            return ToolResult(ok=False, error=ErrorInfo(code="INVALID_REQUEST", message=f"Unknown conditions topic: {topic}", retryable=False))
        path = self.data_path / self.mode / f"{topic}.json"
        try:
            payload = await asyncio.to_thread(self._read, path)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            if self.mode == "live":
                return ToolResult(ok=True, data=ConditionsResult(topic=topic, text=None, source_urls=[], verified_at=None, status="unknown", source_kind="ekt"))
            return ToolResult(ok=False, error=ErrorInfo(code="SOURCE_UNAVAILABLE", message=f"Conditions data is unavailable for {topic}", retryable=True))
        try:
            data = ConditionsResult.model_validate_json(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            return ToolResult(ok=False, error=ErrorInfo(code="INVALID_SOURCE_DATA", message=f"Invalid conditions record: {exc}", retryable=False))
        return ToolResult(ok=True, data=data)

    @staticmethod
    def _read(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)


__all__ = ["ConditionsService"]
