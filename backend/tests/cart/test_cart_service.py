from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def make_product(
    product_id: str = "p1",
    price: str = "1200.00",
    unit: str = "pcs",
    quantity_step: str = "1",
) -> Product:
    return Product(
        product_id=product_id,
        article="ART-1",
        name="<script>alert('xss')</script> Автомат & Тест",
        description="Тестовый товар",
        category="demo_breaker",
        brand="EKT-TEST",
        price=Decimal(price) if price is not None else None,
        unit=unit,
        quantity_step=Decimal(quantity_step) if quantity_step is not None else None,
        specs={"poles": "1"},
        product_url=None,
        certificate_urls=[],
        data_issues=[],
        source_kind="synthetic",
        fetched_at=NOW,
    )


def make_stock(
    product_id: str = "p1",
    warehouse_id: str = "w1",
    quantity: str = "5",
    eligible: bool = True,
) -> StockResult:
    return StockResult(
        product_id=product_id,
        warehouse_id=warehouse_id,
        warehouse_name="Склад 1",
        quantity=Decimal(quantity) if quantity is not None else None,
        warehouse_eligible=eligible,
        fetched_at=NOW,
        source_kind="synthetic",
        source_mode="fixture",
    )


class MockCatalog:
    def __init__(self, product: Product, stock: StockResult):
        self.product = product
        self.stock = stock
        self.calls = 0

    async def get_snapshot(self, product_id: str, warehouse_id: str, refresh: bool = False):
        self.calls += 1
        return ToolResult(
            ok=True,
            data=ProductSnapshot(product=self.product, stock=self.stock),
        )


@pytest_asyncio.fixture
async def cart_env(tmp_path):
    catalog = MockCatalog(make_product(), make_stock(quantity="5"))
    service = CartService(tmp_path / "cart.sqlite", catalog, CartSettings())
    await service.initialize()
    ctx = SessionContext(session_id="session-test-1")
    yield service, catalog, ctx, tmp_path / "cart.sqlite"
    await service.close()


# 4. Валидация единиц и кратности
@pytest.mark.asyncio
async def test_step_and_unit_validation(tmp_path):
    ctx = SessionContext(session_id="s1")

    # step = 0.5 (fractional step -> UNSUPPORTED_SALE_UNIT, no 500)
    p_half = make_product(quantity_step="0.5")
    s = make_stock()
    srv = CartService(tmp_path / "c1.sqlite", MockCatalog(p_half, s), CartSettings())
    await srv.initialize()
    r = await srv.prepare_action(ctx, "p1", "w1", 1)
    assert not r.ok
    assert r.error.code == "UNSUPPORTED_SALE_UNIT"

    # step = 1.5 (fractional step -> UNSUPPORTED_SALE_UNIT)
    p_one_half = make_product(quantity_step="1.5")
    srv = CartService(tmp_path / "c2.sqlite", MockCatalog(p_one_half, s), CartSettings())
    await srv.initialize()
    r = await srv.prepare_action(ctx, "p1", "w1", 3)
    assert not r.ok
    assert r.error.code == "UNSUPPORTED_SALE_UNIT"

    # step = 0 or negative -> UNSUPPORTED_SALE_UNIT
    # PositiveDecimal in contracts requires > 0, so if Decimal("0") is used directly
    # we test validation in _validate_snapshot
    snap_zero = ProductSnapshot(product=make_product(), stock=s)
    # mock quantity_step to Decimal(0)
    snap_zero.product.__dict__["quantity_step"] = Decimal("0")
    assert CartService._validate_snapshot(snap_zero, 1).error.code == "UNSUPPORTED_SALE_UNIT"

    # step unknown (None) -> INVALID_SOURCE_DATA
    snap_none = ProductSnapshot(product=make_product(), stock=s)
    snap_none.product.__dict__["quantity_step"] = None
    assert CartService._validate_snapshot(snap_none, 1).error.code == "INVALID_SOURCE_DATA"

    # unit != 'pcs' (e.g. 'm') -> UNSUPPORTED_SALE_UNIT
    p_meters = make_product(unit="m")
    srv = CartService(tmp_path / "c3.sqlite", MockCatalog(p_meters, s), CartSettings())
    await srv.initialize()
    r = await srv.prepare_action(ctx, "p1", "w1", 1)
    assert not r.ok
    assert r.error.code == "UNSUPPORTED_SALE_UNIT"

    # step = 1 -> valid
    p1 = make_product(quantity_step="1")
    srv = CartService(tmp_path / "c4.sqlite", MockCatalog(p1, s), CartSettings())
    await srv.initialize()
    r = await srv.prepare_action(ctx, "p1", "w1", 2)
    assert r.ok
    assert r.data.quantity_to_add == 2

    # step = 2, quantity = 4 -> valid
    p2 = make_product(quantity_step="2")
    srv = CartService(tmp_path / "c5.sqlite", MockCatalog(p2, s), CartSettings())
    await srv.initialize()
    r = await srv.prepare_action(ctx, "p1", "w1", 4)
    assert r.ok

    # step = 2, quantity = 3 -> INVALID_QUANTITY (not multiple of step)
    r = await srv.prepare_action(ctx, "p1", "w1", 3)
    assert not r.ok
    assert r.error.code == "INVALID_QUANTITY"


# 5. Проверка остатка при prepare_action
@pytest.mark.asyncio
async def test_prepare_action_stock_limits(cart_env):
    service, catalog, ctx, _ = cart_env
    # stock = 5

    # 1. quantity > stock (10 > 5) -> INSUFFICIENT_STOCK
    r_over = await service.prepare_action(ctx, "p1", "w1", 10)
    assert not r_over.ok
    assert r_over.error.code == "INSUFFICIENT_STOCK"

    # Cart must not have any items
    cart = await service.get_cart(ctx)
    assert len(cart.data.items) == 0

    # 2. Exactly available stock (5 == 5) -> OK
    r_exact = await service.prepare_action(ctx, "p1", "w1", 5)
    assert r_exact.ok
    assert r_exact.data.quantity_to_add == 5

    # Now confirm this proposal
    c_res = await service.confirm_action(ctx, r_exact.data.action_id)
    assert c_res.ok
    assert len(c_res.data.cart.items) == 1
    assert c_res.data.cart.items[0].quantity == 5

    # 3. Completely exhausted stock (5 in cart, stock is 5) -> requesting 1 fails
    r_exhausted = await service.prepare_action(ctx, "p1", "w1", 1)
    assert not r_exhausted.ok
    assert r_exhausted.error.code == "INSUFFICIENT_STOCK"

    # 4. Partially filled cart: reset stock to 10
    catalog.stock = make_stock(quantity="10")
    # Now in cart: 5, stock: 10. Remaining: 5.
    # Requesting 5 -> OK (5 + 5 <= 10)
    r_part = await service.prepare_action(ctx, "p1", "w1", 5)
    assert r_part.ok

    # Requesting 6 -> INSUFFICIENT_STOCK (5 + 6 > 10)
    # And check that failed prepare does NOT replace the valid r_part pending action!
    r_fail = await service.prepare_action(ctx, "p1", "w1", 6)
    assert not r_fail.ok
    assert r_fail.error.code == "INSUFFICIENT_STOCK"

    current_pending = await service.get_pending_action(ctx)
    assert current_pending.ok
    assert current_pending.data.action is not None
    assert current_pending.data.action.action_id == r_part.data.action_id


# 2 & 9. cart_url валиден сразу после confirm, already_applied при повторе
@pytest.mark.asyncio
async def test_confirm_without_prior_get_cart_and_idempotency(cart_env):
    service, catalog, ctx, _ = cart_env

    # Prepare action without ever calling get_cart()
    prep = await service.prepare_action(ctx, "p1", "w1", 2)
    assert prep.ok

    # Confirm
    conf = await service.confirm_action(ctx, prep.data.action_id)
    assert conf.ok
    assert conf.data.already_applied is False
    assert conf.data.cart.cart_url.startswith("http://localhost:8000/cart/view/")

    # Extract token
    token = conf.data.cart.cart_url.split("/cart/view/")[1]

    # Open cart view directly
    status, html_content = await service.render_view(token)
    assert status == 200
    assert "2 шт." in html_content
    assert "2400.00 KZT" in html_content
    # XSS escaping check
    assert "<script>" not in html_content
    assert "&lt;script&gt;" in html_content

    # Repeat confirm for the same action_id
    conf2 = await service.confirm_action(ctx, prep.data.action_id)
    assert conf2.ok
    assert conf2.data.already_applied is True
    # Exactly one item in cart, quantity unchanged
    assert len(conf2.data.cart.items) == 1
    assert conf2.data.cart.items[0].quantity == 2


# 11. Дополнительные гарантии CartService
@pytest.mark.asyncio
async def test_token_stored_only_as_hash_in_db(cart_env):
    service, _, ctx, db_path = cart_env
    prep = await service.prepare_action(ctx, "p1", "w1", 1)
    conf = await service.confirm_action(ctx, prep.data.action_id)
    raw_token = conf.data.cart.cart_url.split("/cart/view/")[1]

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT token_hash FROM cart_views").fetchall()
    con.close()

    hashes = [r[0] for r in rows]
    # Raw token must NOT be stored in cleartext
    assert raw_token not in hashes
    # But hash of raw token must match
    import hashlib

    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert expected_hash in hashes


@pytest.mark.asyncio
async def test_foreign_action_id_not_found(cart_env):
    service, _, ctx1, _ = cart_env
    ctx2 = SessionContext(session_id="session-user-2")

    prep = await service.prepare_action(ctx1, "p1", "w1", 1)
    # User 2 tries to confirm User 1's action_id
    res = await service.confirm_action(ctx2, prep.data.action_id)
    assert not res.ok
    assert res.error.code == "ACTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_terms_changed_requires_new_proposal(cart_env):
    service, catalog, ctx, _ = cart_env
    prep = await service.prepare_action(ctx, "p1", "w1", 1)

    # Price changes before confirm
    catalog.product = make_product(price="1500.00")
    res = await service.confirm_action(ctx, prep.data.action_id)
    assert not res.ok
    assert res.error.code == "PRICE_CHANGED"

    # Status in actions must be invalidated
    p_act = await service.get_pending_action(ctx)
    assert p_act.data.action is None


@pytest.mark.asyncio
async def test_source_unavailable_does_not_mutate_cart(cart_env):
    service, catalog, ctx, _ = cart_env
    prep = await service.prepare_action(ctx, "p1", "w1", 1)

    # Mock catalog failure
    async def fail_get_snapshot(*args, **kwargs):
        from app.contracts import ErrorInfo
        return ToolResult(ok=False, error=ErrorInfo(code="SOURCE_UNAVAILABLE", message="EKT down", retryable=True))

    catalog.get_snapshot = fail_get_snapshot
    res = await service.confirm_action(ctx, prep.data.action_id)
    assert not res.ok
    assert res.error.code == "SOURCE_UNAVAILABLE"

    # Cart remains empty
    cart = await service.get_cart(ctx)
    assert len(cart.data.items) == 0


@pytest.mark.asyncio
async def test_repeat_committed_works_after_ttl_without_catalog_call(cart_env):
    service, catalog, ctx, _ = cart_env
    prep = await service.prepare_action(ctx, "p1", "w1", 1)
    res = await service.confirm_action(ctx, prep.data.action_id)
    assert res.ok

    calls_before = catalog.calls
    # Even if catalog would fail or TTL expired:
    async def fail_catalog(*args, **kwargs):
        raise RuntimeError("Catalog should not be called!")

    catalog.get_snapshot = fail_catalog

    # Repeat confirm
    repeat = await service.confirm_action(ctx, prep.data.action_id)
    assert repeat.ok
    assert repeat.data.already_applied is True
    assert catalog.calls == calls_before
