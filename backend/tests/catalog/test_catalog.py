from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.catalog import CatalogService
from app.contracts import SearchFilters, SpecFilter


@dataclass
class FixtureSettings:
    catalog_mode: str = "fixture"
    fixture_catalog_path: Path = Path(__file__).resolve().parents[2] / "data" / "catalog" / "fixture.json"
    ekt_timeout_seconds: int = 1


@pytest.fixture
async def catalog(tmp_path):
    service = CatalogService(tmp_path / "catalog.sqlite", FixtureSettings())
    await service.initialize()
    yield service
    await service.close()


@pytest.mark.asyncio
async def test_fixture_has_canonical_products_and_stock_zero_is_not_unknown(catalog):
    warehouses = await catalog.list_warehouses()
    assert warehouses.ok
    assert warehouses.data.warehouses[0].warehouse_id == "demo-warehouse"

    product = await catalog.get_product("demo-002")
    stock = await catalog.check_stock("demo-002", "demo-warehouse")
    assert product.data.article == "DEMO-002"
    assert stock.data.quantity == 0
    assert stock.data.warehouse_eligible is True


@pytest.mark.asyncio
async def test_fixture_analog_rules_accept_demo_003_and_reject_zero_stock(catalog):
    result = await catalog.find_analogs("demo-002", "demo-warehouse")
    assert result.ok
    assert [candidate.product.product_id for candidate in result.data.candidates] == ["demo-003"]
    assert set(result.data.candidates[0].matched_specs) == {
        "poles",
        "rated_current_a",
        "trip_curve",
        "breaking_capacity_ka",
    }


@pytest.mark.asyncio
async def test_search_is_parameterized_and_unknown_spec_filter_is_rejected(catalog):
    result = await catalog.search_products("DEMO-00", SearchFilters(), limit=2)
    assert result.ok
    assert len(result.data.products) == 2
    assert result.data.warnings

    invalid = await catalog.search_products(
        "DEMO", SearchFilters(specs=[SpecFilter(key="drop table products", value="x")])
    )
    assert not invalid.ok
    assert invalid.error.code == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_certificate_and_missing_warehouse_are_honest(catalog):
    certificate = await catalog.get_certificate("demo-001")
    assert certificate.data.status == "found"
    assert certificate.data.urls == ["/demo-certificates/DEMO-CERT-001.html"]

    missing = await catalog.check_stock("demo-001", "missing-warehouse")
    assert not missing.ok
    assert missing.error.code == "WAREHOUSE_NOT_FOUND"
