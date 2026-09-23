"""CatalogPort implementation for fixture and live modes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.catalog import storage
from app.catalog.fixture import load_fixture
from app.catalog.live import LiveProvider
from app.contracts import (
    AnalogCandidate,
    AnalogResult,
    CertificateResult,
    ErrorInfo,
    Product,
    ProductSnapshot,
    SearchFilters,
    SearchResult,
    StockResult,
    ToolResult,
    Warehouse,
    WarehouseList,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(data: Any) -> ToolResult:
    return ToolResult(ok=True, data=data)


def _error(code: str, message: str, retryable: bool = False) -> ToolResult:
    return ToolResult(ok=False, error=ErrorInfo(code=code, message=message, retryable=retryable))


def _product(value: dict[str, Any]) -> Product:
    # JSON validation permits the ISO timestamp representation while keeping
    # strict Python-side DTOs for callers.
    return Product.model_validate_json(json.dumps(value, ensure_ascii=False))


def _stock(value: dict[str, Any]) -> StockResult:
    return StockResult.model_validate_json(json.dumps(value, ensure_ascii=False))


class CatalogService:
    """A mode-isolated catalog with a canonical synthetic provider."""

    _allowed_spec_keys = {"poles", "rated_current_a", "trip_curve", "breaking_capacity_ka"}
    _required_analog_specs = ("poles", "rated_current_a", "trip_curve", "breaking_capacity_ka")

    def __init__(self, db_path: str | Path, settings: Any) -> None:
        self.db_path = Path(db_path)
        self.settings = settings
        self.mode = getattr(settings, "catalog_mode", "fixture")
        self._client: httpx.AsyncClient | None = None
        self._provider: LiveProvider | None = None
        self._initialized = False

    async def initialize(self) -> None:
        await asyncio.to_thread(storage.initialize, self.db_path)
        if self.mode == "fixture":
            fixture_path = Path(getattr(self.settings, "fixture_catalog_path", Path(__file__).resolve().parents[2] / "data" / "catalog" / "fixture.json"))
            records = await asyncio.to_thread(load_fixture, fixture_path)
            await asyncio.to_thread(storage.replace_catalog, self.db_path, records)
        elif self.mode == "live":
            timeout = float(getattr(self.settings, "ekt_timeout_seconds", 10))
            self._client = httpx.AsyncClient(timeout=timeout)
            self._provider = LiveProvider(
                self._client,
                str(getattr(self.settings, "ekt_base_url", "https://ekt.kz")),
                getattr(self.settings, "ekt_api_username", None),
                getattr(self.settings, "ekt_api_password", None),
            )
        else:
            raise ValueError("catalog mode must be fixture or live")
        self._initialized = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._provider = None
        self._initialized = False

    async def _rows(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return await asyncio.to_thread(storage.read_rows, self.db_path, sql, parameters)

    async def _save_live(self, product: dict[str, Any], raw: Any, full_payload: Any, stocks: list[dict[str, Any]], warehouses: list[dict[str, Any]]) -> None:
        provenance = {"source_field": "EKT /api/products/detail", "transformation": "normalized from one successful detail response", "fetched_at": product["fetched_at"], "raw_response_saved": True}
        records_stocks = []
        for stock in stocks:
            item = dict(stock["value"])
            warehouse = item.pop("warehouse", None)
            if warehouse is not None:
                item["warehouse"] = warehouse
            records_stocks.append({"warehouse_id": item["warehouse_id"], "value": item, "raw": raw, "provenance": provenance})
        await asyncio.to_thread(storage.upsert_product, self.db_path, product, full_payload, provenance, records_stocks, warehouses)

    async def _fetch_live(self, product_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Any, Any] | ToolResult:
        if self._provider is None:
            return _error("SOURCE_UNAVAILABLE", "Live catalog provider is not initialized", True)
        try:
            result, full_payload, raw = await self._provider.fetch_product(product_id)
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _error("SOURCE_UNAVAILABLE", f"EKT detail is unavailable: {exc}", True)
        return result["product"], result["stocks"], result["warehouses"], raw, full_payload

    async def list_warehouses(self) -> ToolResult[WarehouseList]:
        rows = await self._rows("SELECT warehouse_json FROM catalog_warehouses ORDER BY warehouse_id")
        warehouses = [Warehouse.model_validate_json(row["warehouse_json"]) for row in rows]
        return _ok(WarehouseList(warehouses=warehouses))

    async def search_products(self, query: str, filters: SearchFilters, limit: int = 5) -> ToolResult[SearchResult]:
        if not isinstance(query, str) or not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > 50:
            return _error("INVALID_REQUEST", "query must be text and limit must be between 1 and 50")
        for item in filters.specs:
            if item.key not in self._allowed_spec_keys:
                return _error("INVALID_REQUEST", f"Unknown specification filter: {item.key}")
        term = query.strip()
        if term:
            escaped = term.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            rows = await self._rows(
                "SELECT product_json FROM catalog_products WHERE article_folded LIKE ? ESCAPE '\\' OR name_folded LIKE ? ESCAPE '\\' ORDER BY product_id",
                (pattern, pattern),
            )
        else:
            rows = await self._rows("SELECT product_json FROM catalog_products ORDER BY product_id")
        products: list[Product] = []
        for row in rows:
            product = _product(json.loads(row["product_json"]))
            if filters.category is not None and product.category != filters.category:
                continue
            if filters.brand is not None and product.brand != filters.brand:
                continue
            if any(product.specs.get(item.key) != item.value for item in filters.specs):
                continue
            products.append(product)
        warnings = ["Выборка ограничена локально доступными данными каталога."]
        if len(products) > limit:
            warnings.append(f"Результат ограничен первыми {limit} товарами.")
        return _ok(SearchResult(products=products[:limit], warnings=warnings))

    async def get_product(self, product_id: str, refresh: bool = False) -> ToolResult[Product]:
        product_id = str(product_id).strip()
        if not product_id:
            return _error("INVALID_REQUEST", "product_id is required")
        if refresh and self.mode == "live":
            fetched = await self._fetch_live(product_id)
            if isinstance(fetched, ToolResult):
                return fetched
            product, stocks, warehouses, raw, full_payload = fetched
            await self._save_live(product, raw, full_payload, stocks, warehouses)
            return _ok(_product(product))
        rows = await self._rows("SELECT product_json FROM catalog_products WHERE product_id = ?", (product_id,))
        if not rows:
            return _error("PRODUCT_NOT_FOUND", f"Product {product_id} was not found")
        return _ok(_product(json.loads(rows[0]["product_json"])))

    async def check_stock(self, product_id: str, warehouse_id: str, refresh: bool = False) -> ToolResult[StockResult]:
        product_id, warehouse_id = str(product_id).strip(), str(warehouse_id).strip()
        if refresh and self.mode == "live":
            fetched = await self._fetch_live(product_id)
            if isinstance(fetched, ToolResult):
                return fetched
            product, stocks, warehouses, raw, full_payload = fetched
            await self._save_live(product, raw, full_payload, stocks, warehouses)
            match = next((item["value"] for item in stocks if item["value"]["warehouse_id"] == warehouse_id), None)
            if match is None:
                return _error("WAREHOUSE_NOT_FOUND", f"Warehouse {warehouse_id} was not present in the fresh detail response")
            match.pop("warehouse", None)
            match.pop("data_issues", None)
            return _ok(_stock(match))
        rows = await self._rows("SELECT stock_json FROM catalog_stocks WHERE product_id = ? AND warehouse_id = ?", (product_id, warehouse_id))
        if not rows:
            product_rows = await self._rows("SELECT product_id FROM catalog_products WHERE product_id = ?", (product_id,))
            if not product_rows:
                return _error("PRODUCT_NOT_FOUND", f"Product {product_id} was not found")
            return _error("WAREHOUSE_NOT_FOUND", f"Warehouse {warehouse_id} was not found for product {product_id}")
        value = json.loads(rows[0]["stock_json"])
        value.pop("data_issues", None)
        value.pop("warehouse", None)
        return _ok(_stock(value))

    async def get_snapshot(self, product_id: str, warehouse_id: str, refresh: bool = False) -> ToolResult[ProductSnapshot]:
        if refresh and self.mode == "live":
            fetched = await self._fetch_live(str(product_id).strip())
            if isinstance(fetched, ToolResult):
                return fetched
            product, stocks, warehouses, raw, full_payload = fetched
            await self._save_live(product, raw, full_payload, stocks, warehouses)
            match = next((item["value"] for item in stocks if item["value"]["warehouse_id"] == str(warehouse_id).strip()), None)
            if match is None:
                return _error("WAREHOUSE_NOT_FOUND", "Selected warehouse was absent from the fresh detail response")
            match = dict(match)
            match.pop("warehouse", None)
            match.pop("data_issues", None)
            match["source_mode"] = "snapshot"
            return _ok(ProductSnapshot(product=_product(product), stock=_stock(match)))
        product_result = await self.get_product(product_id, refresh=False)
        if not product_result.ok:
            return product_result
        stock_result = await self.check_stock(product_id, warehouse_id, refresh=False)
        if not stock_result.ok:
            return stock_result
        return _ok(ProductSnapshot(product=product_result.data, stock=stock_result.data))

    async def find_analogs(self, product_id: str, warehouse_id: str, limit: int = 3) -> ToolResult[AnalogResult]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > 20:
            return _error("INVALID_REQUEST", "limit must be between 1 and 20")
        source_result = await self.get_product(product_id)
        if not source_result.ok:
            return source_result
        source = source_result.data
        if source.category != "demo_breaker" or any(key not in source.specs for key in self._required_analog_specs):
            return _ok(AnalogResult(candidates=[], warnings=["Недостаточно обязательных характеристик для обоснованного аналога."]))
        rows = await self._rows("SELECT product_json FROM catalog_products WHERE product_id != ? ORDER BY product_id", (source.product_id,))
        candidates: list[AnalogCandidate] = []
        excluded = []
        for row in rows:
            product = _product(json.loads(row["product_json"]))
            if product.category != source.category or product.data_issues:
                excluded.append(product.product_id)
                continue
            if any(key not in product.specs for key in self._required_analog_specs):
                excluded.append(product.product_id)
                continue
            if any(product.specs[key] != source.specs[key] for key in self._required_analog_specs):
                excluded.append(product.product_id)
                continue
            stock_result = await self.check_stock(product.product_id, warehouse_id)
            if not stock_result.ok or stock_result.data.warehouse_eligible is not True or stock_result.data.quantity is None or stock_result.data.quantity <= 0:
                excluded.append(product.product_id)
                continue
            matched = {key: product.specs[key] for key in self._required_analog_specs}
            differences = []
            if product.price != source.price:
                differences.append(f"price: {source.price} -> {product.price}")
            if product.unit != source.unit:
                differences.append(f"unit: {source.unit} -> {product.unit}")
            limitations = ["Демонстрационное совпадение; реальная взаимозаменяемость не подтверждается."] if product.source_kind == "synthetic" else []
            candidates.append(AnalogCandidate(product=product, stock=stock_result.data, matched_specs=matched, differences=differences, limitations=limitations))
        warnings = ["Правила аналогов проверяют только подтверждённые обязательные характеристики, склад и положительный остаток."]
        if not candidates:
            warnings.append("Обоснованных кандидатов в доступной выборке нет.")
        return _ok(AnalogResult(candidates=candidates[:limit], warnings=warnings))

    async def get_certificate(self, product_id: str) -> ToolResult[CertificateResult]:
        product_result = await self.get_product(product_id)
        if not product_result.ok:
            return product_result
        product = product_result.data
        if product.certificate_urls:
            return _ok(CertificateResult(product_id=product.product_id, urls=product.certificate_urls, status="found"))
        return _ok(CertificateResult(product_id=product.product_id, urls=[], status="not_found_in_available_data"))

    async def import_live_products(self, product_ids: list[str]) -> list[ToolResult[Product]]:
        if self.mode != "live" or not product_ids:
            return [_error("INVALID_REQUEST", "Live import requires CATALOG_MODE=live and at least one product id")]
        results = []
        for product_id in product_ids[:20]:
            results.append(await self.get_product(product_id, refresh=True))
        return results
