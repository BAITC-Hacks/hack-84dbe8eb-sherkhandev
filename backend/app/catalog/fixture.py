"""Fixture provider adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.catalog.normalize import iso, now_utc, normalize_product, normalize_warehouse


def load_fixture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    fetched_at = now_utc()
    warehouses = []
    for raw in payload.get("warehouses", []):
        value = normalize_warehouse(raw, "synthetic", fetched_at)
        warehouses.append({"warehouse_id": value["warehouse_id"], "value": value, "raw": raw, "provenance": {"source_field": "fixture.warehouses", "transformation": "canonical fixture normalization", "source_kind": "synthetic", "fetched_at": iso(fetched_at)}})
    products = []
    for raw in payload.get("products", []):
        value, stocks, product_warehouses = normalize_product(raw, "synthetic", fetched_at)
        products.append({"value": value, "raw": raw, "provenance": {"source_field": "fixture.products", "transformation": "canonical fixture normalization", "fetched_at": value["fetched_at"]}, "stocks": stocks})
        known = {item["warehouse_id"] for item in warehouses}
        for warehouse in product_warehouses:
            if warehouse["warehouse_id"] not in known:
                warehouses.append(warehouse)
    return {"warehouses": warehouses, "products": products}
