"""Conservative EKT HTTP adapter.

The public site/API shape is not assumed to be available.  This adapter keeps
the exact response JSON and only emits a Product when the required identity
fields can be established by the response.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.catalog.normalize import now_utc, normalize_product


class LiveProvider:
    def __init__(self, client: httpx.AsyncClient, base_url: str = "https://ekt.kz") -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def fetch_detail(self, product_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        response = await self.client.get(f"{self.base_url}/api/products/detail", params={"id": product_id})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            raw = payload["data"]
        elif isinstance(payload, dict):
            raw = payload
        else:
            raise ValueError("detail response is not an object")
        if not isinstance(raw, dict):
            raise ValueError("detail data is not an object")
        return raw, payload

    async def fetch_product(self, product_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        raw, full_payload = await self.fetch_detail(product_id)
        fetched_at = now_utc()
        product, stocks, warehouses = normalize_product(raw, "ekt", fetched_at)
        return {"product": product, "stocks": stocks, "warehouses": warehouses}, full_payload, raw
