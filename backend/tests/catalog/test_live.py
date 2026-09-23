from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from app.catalog import CatalogService
from app.catalog.live import LiveProvider
from app.catalog.normalize import normalize_product, now_utc


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
async def test_live_provider_sends_basic_auth_when_configured():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json=detail_payload())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LiveProvider(client, "https://example.invalid", "apiuser", "secret")
    try:
        await provider.fetch_detail("000123")
    finally:
        await client.aclose()

    expected = base64.b64encode(b"apiuser:secret").decode("ascii")
    assert seen["authorization"] == f"Basic {expected}"


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


def stores_payload():
    return {
        "id": "000789",
        "article": "000012",
        "name": "Live breaker with stores",
        "category": "demo_breaker",
        "price": "2500.00",
        "unit": "pcs",
        "quantity_step": "1",
        "specs": {"poles": "1", "rated_current_a": "16", "trip_curve": "C", "breaking_capacity_ka": "6"},
        "stores": [
            {
                "store": {"id": "001", "name": "Store Eligible Zero", "eligible": True},
                "quantity": 0,
            },
            {
                "store": {"id": "002", "name": "Store Unknown Stock", "eligible": False},
                "quantity": None,
            },
            {
                "store": {"id": "003", "name": "Store No Eligible Field"},
                "quantity": "5",
            },
            {
                "store": {"id": "004", "name": "Store Eligible Positive", "eligible": True},
                "quantity": "15",
            },
        ],
    }


def test_live_normalizer_uses_stores_when_empty_offers_are_present():
    raw = stores_payload()
    raw["offers"] = []
    product, stocks, warehouses = normalize_product(raw, "ekt", now_utc())

    assert product["product_id"] == "000789"
    assert len(stocks) == 4
    assert len(warehouses) == 4
    assert stocks[0]["value"]["warehouse_id"] == "001"


@pytest.mark.asyncio
async def test_live_stores_payload_normalizer_and_transport(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=stores_payload())

    service = CatalogService(tmp_path / "catalog.sqlite", LiveSettings())
    await service.initialize()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._client = client
    service._provider = LiveProvider(client, "https://example.invalid")
    try:
        # Known zero stock, eligible=True, leading zeros preserved
        r1 = await service.get_snapshot("000789", "001", refresh=True)
        assert r1.ok
        assert r1.data.product.product_id == "000789"
        assert r1.data.product.article == "000012"
        assert r1.data.stock.warehouse_id == "001"
        assert r1.data.stock.quantity == 0
        assert r1.data.stock.warehouse_eligible is True

        # Unknown stock (None), eligible=False
        r2 = await service.get_snapshot("000789", "002", refresh=False)
        assert r2.ok
        assert r2.data.stock.warehouse_eligible is False
        assert r2.data.stock.quantity is None

        # Stock with no eligible field (unconfirmed eligibility -> None, not True)
        r3 = await service.get_snapshot("000789", "003", refresh=False)
        assert r3.ok
        assert r3.data.stock.warehouse_eligible is None
        assert r3.data.stock.quantity == 5

        # Eligible positive
        r4 = await service.get_snapshot("000789", "004", refresh=False)
        assert r4.ok
        assert r4.data.stock.warehouse_eligible is True
        assert r4.data.stock.quantity == 15

        # Absent warehouse is not zero stock, but WAREHOUSE_NOT_FOUND
        r5 = await service.check_stock("000789", "005", refresh=False)
        assert not r5.ok
        assert r5.error.code == "WAREHOUSE_NOT_FOUND"
    finally:
        await service.close()
