from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app.cart.service import CartService
from app.contracts import (
    Product,
    ProductSnapshot,
    SessionContext,
    StockResult,
    ToolResult,
)

NOW = datetime.now(timezone.utc)


@dataclass
class CartSettings:
    catalog_mode: str = "fixture"
    app_base_url: str = "http://localhost:8000"
    view_ttl_seconds: int = 1800
    action_ttl_seconds: int = 300


def make_product(product_id: str = "p1") -> Product:
    return Product(
        product_id=product_id,
        article="ART-1",
        name="Товар 1",
        description="Тест",
        category="demo_breaker",
        brand="EKT-TEST",
        price=Decimal("1000.00"),
        unit="pcs",
        quantity_step=Decimal("1"),
        specs={"poles": "1"},
        product_url=None,
        certificate_urls=[],
        data_issues=[],
        source_kind="synthetic",
        fetched_at=NOW,
    )


def make_stock(quantity: str = "3") -> StockResult:
    return StockResult(
        product_id="p1",
        warehouse_id="w1",
        warehouse_name="Склад 1",
        quantity=Decimal(quantity),
        warehouse_eligible=True,
        fetched_at=NOW,
        source_kind="synthetic",
        source_mode="fixture",
    )


class MockCatalog:
    def __init__(self, stock_quantity: str = "3"):
        self.product = make_product()
        self.stock = make_stock(stock_quantity)

    async def get_snapshot(self, product_id: str, warehouse_id: str, refresh: bool = False):
        return ToolResult(
            ok=True,
            data=ProductSnapshot(product=self.product, stock=self.stock),
        )


@pytest.mark.asyncio
async def test_concurrent_confirmations_idempotent_and_respect_stock(tmp_path):
    catalog = MockCatalog(stock_quantity="3")
    service = CartService(tmp_path / "cart_concurrency.sqlite", catalog, CartSettings())
    await service.initialize()
    ctx = SessionContext(session_id="session-concurrent-1")

    # Prepare an action to add 2 pcs (stock is 3)
    prep = await service.prepare_action(ctx, "p1", "w1", 2)
    assert prep.ok
    action_id = prep.data.action_id

    # Run two confirms concurrently
    results = await asyncio.gather(
        service.confirm_action(ctx, action_id),
        service.confirm_action(ctx, action_id),
    )

    r1, r2 = results
    assert r1.ok
    assert r2.ok

    # Exactly one must have already_applied=False, and the other already_applied=True
    applied_flags = sorted([r1.data.already_applied, r2.data.already_applied])
    assert applied_flags == [False, True]

    # Verify cart state in DB
    cart = await service.get_cart(ctx)
    assert cart.ok
    assert len(cart.data.items) == 1
    assert cart.data.items[0].quantity == 2
    assert cart.data.total == Decimal("2000.00")

    await service.close()
