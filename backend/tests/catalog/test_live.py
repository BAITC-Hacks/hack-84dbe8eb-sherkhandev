from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from app.catalog import CatalogService
from app.catalog.live import LiveProvider


@dataclass
class LiveSettings:
    catalog_mode: str = "live"
    ekt_timeout_seconds: int = 1
    ekt_base_url: str = "https://example.invalid"


def detail_payload():
    return {
        "id": "000123",
        "article": " 000045 ",
        "name": "Live breaker",
        "category": "demo_breaker",
        "price": "10.25",
        "unit": "pcs",
        "quantity_step": "0.5",
        "specs": {"poles": "1", "rated_current_a": "16", "trip_curve": "C", "breaking_capacity_ka": "6"},
        "offers": [{"warehouse": {"id": "w1", "name": "Sales warehouse", "eligible": True}, "quantity": "1.5"}],
    }


@pytest.mark.asyncio
async def test_live_snapshot_uses_one_detail_response_and_preserves_decimal_values(tmp_path):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=detail_payload())

    service = CatalogService(tmp_path / "catalog.sqlite", LiveSettings())
    await service.initialize()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._client = client
    service._provider = LiveProvider(client, "https://example.invalid")
    try:
        result = await service.get_snapshot("000123", "w1", refresh=True)
        assert result.ok
        assert result.data.product.product_id == "000123"
        assert result.data.product.article == "000045"
        assert result.data.stock.quantity == 1.5
        assert len(calls) == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_live_refresh_failure_does_not_return_old_snapshot(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    service = CatalogService(tmp_path / "catalog.sqlite", LiveSettings())
    await service.initialize()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._client = client
    service._provider = LiveProvider(client, "https://example.invalid")
    try:
        result = await service.get_snapshot("000123", "w1", refresh=True)
        assert not result.ok
        assert result.error.code == "SOURCE_UNAVAILABLE"
    finally:
        await service.close()
