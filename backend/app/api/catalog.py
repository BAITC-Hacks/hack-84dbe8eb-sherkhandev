"""Authenticated catalog HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.contracts import SessionContext, WarehouseList
from app.dependencies import get_catalog_service, get_session_context


router = APIRouter()


def _raise_result(result) -> None:
    error = result.error
    status = 503 if error.code == "SOURCE_UNAVAILABLE" else 400
    raise HTTPException(status_code=status, detail=error.model_dump())


@router.get("/api/v1/warehouses", response_model=WarehouseList)
async def list_warehouses(
    _: SessionContext = Depends(get_session_context),
    catalog=Depends(get_catalog_service),
) -> WarehouseList:
    result = await catalog.list_warehouses()
    if not result.ok:
        _raise_result(result)
    return result.data


__all__ = ["router"]
