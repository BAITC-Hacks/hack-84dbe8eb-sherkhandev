from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from app.catalog import CatalogService
from app.contracts import SearchFilters, SpecFilter


@dataclass
class FixtureSettings:
    catalog_mode: str = "fixture"
    fixture_catalog_path: Path = Path(__file__).resolve().parents[2] / "data" / "catalog" / "fixture.json"
    ekt_timeout_seconds: int = 1


@pytest_asyncio.fixture
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


def test_warehouse_model_rejects_extra_fields():
    from pydantic import ValidationError
    from app.contracts import Warehouse

    with pytest.raises(ValidationError):
        Warehouse.model_validate({"warehouse_id": "w1", "name": "W", "eligible": True, "source_kind": "synthetic"})


@pytest.mark.asyncio
async def test_warehouses_endpoint_with_valid_session_returns_200():
    import httpx
    from app.main import app

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session = await client.post("/api/v1/sessions")
            token = session.json()["session_token"]
            response = await client.get("/api/v1/warehouses", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            data = response.json()
            assert "warehouses" in data
            assert len(data["warehouses"]) >= 1
            assert data["warehouses"][0]["warehouse_id"] == "demo-warehouse"
            assert data["warehouses"][0]["eligible"] is True
            assert set(data["warehouses"][0].keys()) <= {"warehouse_id", "name", "eligible"}


@pytest.mark.asyncio
async def test_unicode_case_insensitive_search(catalog):
    # Russian lower case finds Title Case
    res1 = await catalog.search_products("учебный автомат", SearchFilters())
    assert res1.ok
    assert any("Учебный автомат" in p.name for p in res1.data.products)

    # Russian upper case finds Title Case
    res2 = await catalog.search_products("УЧЕБНЫЙ АВТОМАТ", SearchFilters())
    assert res2.ok
    assert any("Учебный автомат" in p.name for p in res2.data.products)

    # Article search is case-insensitive
    res3 = await catalog.search_products("demo-001", SearchFilters())
    assert res3.ok
    assert any(p.article == "DEMO-001" for p in res3.data.products)

    res4 = await catalog.search_products("DEMO-001", SearchFilters())
    assert res4.ok
    assert any(p.article == "DEMO-001" for p in res4.data.products)

    # Special chars %, _, quotes do not expand search or execute SQL
    res_wildcard = await catalog.search_products("%", SearchFilters())
    assert res_wildcard.ok
    assert len(res_wildcard.data.products) == 0

    res_quote = await catalog.search_products("'; DROP TABLE catalog_products; --", SearchFilters())
    assert res_quote.ok
    assert len(res_quote.data.products) == 0

    # Filters continue to work
    res_filtered = await catalog.search_products(
        "автомат", SearchFilters(category="demo_breaker", brand="EKT-DEMO")
    )
    assert res_filtered.ok
    assert len(res_filtered.data.products) > 0
