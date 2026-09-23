"""Normalization of fixture and provider payloads.

The normalizer is deliberately conservative.  A missing or malformed source
number becomes ``None`` plus a data issue; it is never silently rounded or
turned into zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


SPEC_KEYS = {"poles", "rated_current_a", "trip_curve", "breaking_capacity_ka"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, *, strip: bool = True) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return None
    result = str(value)
    return result.strip() if strip else result


def decimal_text(value: Any, *, non_negative: bool = True) -> tuple[str | None, str | None]:
    if value is None or isinstance(value, bool):
        return None, "missing or non-numeric value"
    if isinstance(value, float):
        return None, "binary float is not accepted as source decimal"
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None, "invalid decimal value"
    if not number.is_finite():
        return None, "non-finite decimal value"
    if non_negative and number < 0:
        return None, "negative decimal value"
    return format(number, "f"), None


def _properties(raw: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    issues: list[str] = []
    values: dict[str, str] = {}
    properties = raw.get("specs", raw.get("properties", {}))
    if isinstance(properties, list):
        converted: dict[str, Any] = {}
        for item in properties:
            if isinstance(item, dict):
                key = item.get("key", item.get("name"))
                value = item.get("value")
                if key is not None:
                    converted[str(key)] = value
        properties = converted
    if not isinstance(properties, dict):
        properties = {}
        if raw.get("properties") is not None or raw.get("specs") is not None:
            issues.append("properties are not an object")
    for key, value in properties.items():
        key_text = _text(key)
        value_text = _text(value)
        if key_text and value_text is not None:
            values[key_text] = value_text
    for key in SPEC_KEYS:
        if key in raw:
            direct = _text(raw[key])
            if direct is not None and key in values and values[key] != direct:
                issues.append(f"conflicting value for spec {key}")
            elif direct is not None:
                values[key] = direct
    return values, issues


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def normalize_warehouse(raw: dict[str, Any], source_kind: str | None = None, fetched_at: datetime | None = None) -> dict[str, Any]:
    warehouse_id = _text(_first(raw, "warehouse_id", "id", "code", "store_id"))
    name = _text(_first(raw, "name", "title", "warehouse_name", "store_name"))
    if not warehouse_id or not name:
        raise ValueError("warehouse requires id and name")
    eligible = raw.get("eligible") if isinstance(raw.get("eligible"), bool) else None
    return {
        "warehouse_id": warehouse_id,
        "name": name,
        "eligible": eligible,
    }


def normalize_product(raw: dict[str, Any], source_kind: str, fetched_at: datetime) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    product_id = _text(_first(raw, "product_id", "id", "productId"))
    article = _text(_first(raw, "article", "sku", "vendor_code", "vendorCode"))
    name = _text(_first(raw, "name", "title"))
    if not product_id or not article or not name:
        raise ValueError("product requires product_id, article and name")
    issues: list[str] = []
    price, price_issue = decimal_text(_first(raw, "price", "unit_price", "unitPrice"))
    if price_issue and _first(raw, "price", "unit_price", "unitPrice") is not None:
        issues.append(f"price: {price_issue}")
    step, step_issue = decimal_text(_first(raw, "quantity_step", "quantityStep", "step"))
    if step is not None and Decimal(step) <= 0:
        step, step_issue = None, "quantity step must be positive"
    if step_issue and _first(raw, "quantity_step", "quantityStep", "step") is not None:
        issues.append(f"quantity_step: {step_issue}")
    specs, spec_issues = _properties(raw)
    issues.extend(spec_issues)
    description = _text(raw.get("description"))
    category = _text(raw.get("category"))
    brand = _text(raw.get("brand"))
    certificates = raw.get("certificate_urls", raw.get("certificates", []))
    if not isinstance(certificates, list):
        certificates = []
        issues.append("certificate_urls are not a list")
    product = {
        "product_id": product_id,
        "article": article,
        "name": name,
        "description": description,
        "category": category,
        "brand": brand,
        "price": price,
        "currency": "KZT",
        "unit": _text(raw.get("unit")),
        "quantity_step": step,
        "specs": specs,
        "product_url": _text(raw.get("product_url", raw.get("url"))),
        "certificate_urls": [str(item) for item in certificates if isinstance(item, str)],
        "data_issues": issues,
        "source_kind": source_kind,
        "fetched_at": iso(fetched_at),
    }
    warehouses: list[dict[str, Any]] = []
    stocks: list[dict[str, Any]] = []
    raw_stocks = _first(raw, "stocks", "warehouses", "offers", "stores") or []
    if isinstance(raw_stocks, dict):
        raw_stocks = [raw_stocks]
    if isinstance(raw_stocks, list):
        for item in raw_stocks:
            if not isinstance(item, dict):
                continue
            warehouse_raw = item.get("warehouse", item.get("store", item))
            try:
                warehouse = normalize_warehouse(warehouse_raw, source_kind, fetched_at)
            except ValueError:
                continue
            item_eligible = item.get("eligible") if isinstance(item.get("eligible"), bool) else warehouse_raw.get("eligible") if isinstance(warehouse_raw.get("eligible"), bool) else None
            if item_eligible is not None:
                warehouse["eligible"] = item_eligible
            warehouses.append({
                "warehouse_id": warehouse["warehouse_id"],
                "value": warehouse,
                "raw": warehouse_raw,
                "provenance": {
                    "source_field": "warehouse/store",
                    "transformation": "normalized id/name/eligible",
                    "source_kind": source_kind,
                    "fetched_at": iso(fetched_at),
                },
            })
            quantity_val = _first(item, "quantity", "stock", "available", "count")
            quantity, quantity_issue = decimal_text(quantity_val)
            stock_issues = [] if not quantity_issue or quantity_val is None else [quantity_issue]
            stock = {
                "product_id": product_id,
                "warehouse_id": warehouse["warehouse_id"],
                "warehouse_name": warehouse["name"],
                "quantity": quantity,
                "warehouse_eligible": warehouse.get("eligible"),
                "fetched_at": iso(fetched_at),
                "source_kind": source_kind,
                "source_mode": "fixture" if source_kind == "synthetic" else "live",
                "data_issues": stock_issues,
                "warehouse": warehouse,
            }
            stocks.append({
                "warehouse_id": warehouse["warehouse_id"],
                "value": stock,
                "raw": item,
                "provenance": {
                    "source_field": "quantity/stock/available/count",
                    "transformation": "validated non-negative decimal; unknown stays null",
                    "source_kind": source_kind,
                    "fetched_at": iso(fetched_at),
                },
            })
    return product, stocks, warehouses
