from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.catalog import router
from app.contracts import Warehouse, WarehouseList, ToolResult
from app.dependencies import get_catalog_service, get_session_context


class FakeCatalog:
    async def list_warehouses(self):
        return ToolResult(ok=True, data=WarehouseList(warehouses=[Warehouse(warehouse_id="w1", name="Warehouse", eligible=True)]))


def test_warehouses_requires_common_bearer_dependency_and_returns_dto():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_catalog_service] = lambda: FakeCatalog()
    app.dependency_overrides[get_session_context] = lambda: object()
    client = TestClient(app)

    response = client.get("/api/v1/warehouses")
    assert response.status_code == 200
    assert response.json() == {"warehouses": [{"warehouse_id": "w1", "name": "Warehouse", "eligible": True}]}
