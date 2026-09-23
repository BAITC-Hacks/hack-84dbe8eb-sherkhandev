"""Shared DTOs and asynchronous service contracts for EKT AI.

This module is the only owner of cross-module Python models.  Decimal values
remain Decimal in Python and are rendered as finite decimal strings in JSON.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.functional_validators import BeforeValidator
from typing_extensions import Annotated


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("decimal values must be finite decimal strings or Decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid decimal value") from exc
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


DecimalValue = Annotated[Decimal, BeforeValidator(_decimal)]
NonNegativeDecimal = Annotated[DecimalValue, Field(ge=Decimal("0"))]
PositiveDecimal = Annotated[DecimalValue, Field(gt=Decimal("0"))]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class SessionContext(ContractModel):
    session_id: str = Field(min_length=1)


class SessionCreated(ContractModel):
    session_id: str = Field(min_length=1)
    session_token: str = Field(min_length=32)


class Warehouse(ContractModel):
    warehouse_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    eligible: bool | None = None


class WarehouseList(ContractModel):
    warehouses: list[Warehouse]


class Product(ContractModel):
    product_id: str = Field(min_length=1)
    article: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    price: NonNegativeDecimal | None = None
    currency: Literal["KZT"] = "KZT"
    unit: str | None = None
    quantity_step: PositiveDecimal | None = None
    specs: dict[str, str]
    product_url: str | None = None
    certificate_urls: list[str]
    data_issues: list[str]
    source_kind: Literal["ekt", "synthetic"]
    fetched_at: datetime


class StockResult(ContractModel):
    product_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    warehouse_name: str = Field(min_length=1)
    quantity: NonNegativeDecimal | None = None
    warehouse_eligible: bool | None = None
    fetched_at: datetime
    source_kind: Literal["ekt", "synthetic"]
    source_mode: Literal["live", "snapshot", "fixture"]


class ProductSnapshot(ContractModel):
    product: Product
    stock: StockResult


class SpecFilter(ContractModel):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class SearchFilters(ContractModel):
    category: str | None = None
    brand: str | None = None
    specs: list[SpecFilter] = Field(default_factory=list)


class SearchResult(ContractModel):
    products: list[Product]
    coverage: Literal["partial"] = "partial"
    warnings: list[str]


class AnalogCandidate(ContractModel):
    product: Product
    stock: StockResult
    matched_specs: dict[str, str]
    differences: list[str]
    limitations: list[str]


class AnalogResult(ContractModel):
    candidates: list[AnalogCandidate]
    warnings: list[str]


class CertificateResult(ContractModel):
    product_id: str = Field(min_length=1)
    urls: list[str]
    status: Literal["found", "not_found_in_available_data"]


class ConditionsResult(ContractModel):
    topic: Literal["payment", "delivery", "minimum_order"]
    text: str | None = None
    source_urls: list[str]
    verified_at: datetime | None = None
    status: Literal["known", "unknown"]
    source_kind: Literal["ekt", "synthetic"]


class PendingAction(ContractModel):
    action_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    quantity_to_add: int = Field(gt=0)
    unit_price: NonNegativeDecimal
    added_amount: NonNegativeDecimal
    currency: Literal["KZT"] = "KZT"
    unit: str = Field(min_length=1)
    quantity_step: PositiveDecimal
    stock_quantity: NonNegativeDecimal
    checked_at: datetime
    expires_at: datetime
    status: Literal["pending"] = "pending"
    source_kind: Literal["ekt", "synthetic"]

    @field_validator("quantity_to_add", mode="before")
    @classmethod
    def _strict_positive_int(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("quantity_to_add must be a positive integer")
        return value

    @model_validator(mode="after")
    def _validate_amount_and_dates(self) -> "PendingAction":
        if self.added_amount != self.unit_price * self.quantity_to_add:
            raise ValueError("added_amount must equal unit_price * quantity_to_add")
        if self.expires_at <= self.checked_at:
            raise ValueError("expires_at must be after checked_at")
        return self


class PendingActionResult(ContractModel):
    action: PendingAction | None = None


class CartItem(ContractModel):
    line_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price_at_addition: NonNegativeDecimal
    line_total: NonNegativeDecimal
    source_action_id: str = Field(min_length=1)

    @field_validator("quantity", mode="before")
    @classmethod
    def _strict_quantity(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("quantity must be a positive integer")
        return value

    @model_validator(mode="after")
    def _validate_line_total(self) -> "CartItem":
        if self.line_total != self.unit_price_at_addition * self.quantity:
            raise ValueError("line_total must equal unit_price_at_addition * quantity")
        return self


class Cart(ContractModel):
    cart_id: str = Field(min_length=1)
    items: list[CartItem]
    total: NonNegativeDecimal
    currency: Literal["KZT"] = "KZT"
    mode: Literal["demo"] = "demo"
    data_mode: Literal["live", "fixture"]
    cart_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_total(self) -> "Cart":
        if self.total != sum((item.line_total for item in self.items), Decimal("0")):
            raise ValueError("cart total must equal the sum of line totals")
        return self


class ConfirmResult(ContractModel):
    action_id: str = Field(min_length=1)
    already_applied: bool
    cart: Cart


class ChatRequest(ContractModel):
    message: str = Field(min_length=1, max_length=4000)
    warehouse_id: str | None = None
    confirmation_action_id: str | None = None

    @field_validator("message")
    @classmethod
    def _non_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class ChatResponse(ContractModel):
    message: str = Field(min_length=1)
    products: list[Product] = Field(default_factory=list)
    pending_action: PendingAction | None = None
    cart: Cart | None = None
    warnings: list[str] = Field(default_factory=list)


class ErrorInfo(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


T = TypeVar("T")


class ToolResult(ContractModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def _one_payload_side(self) -> "ToolResult[T]":
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("successful ToolResult must contain only data")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("failed ToolResult must contain only error")
        return self


class CatalogPort(Protocol):
    async def list_warehouses(self) -> ToolResult[WarehouseList]: ...
    async def search_products(self, query: str, filters: SearchFilters, limit: int = 5) -> ToolResult[SearchResult]: ...
    async def get_product(self, product_id: str, refresh: bool = False) -> ToolResult[Product]: ...
    async def check_stock(self, product_id: str, warehouse_id: str, refresh: bool = False) -> ToolResult[StockResult]: ...
    async def get_snapshot(self, product_id: str, warehouse_id: str, refresh: bool = False) -> ToolResult[ProductSnapshot]: ...
    async def find_analogs(self, product_id: str, warehouse_id: str, limit: int = 3) -> ToolResult[AnalogResult]: ...
    async def get_certificate(self, product_id: str) -> ToolResult[CertificateResult]: ...


class CartPort(Protocol):
    async def prepare_action(self, context: SessionContext, product_id: str, warehouse_id: str, quantity_to_add: int) -> ToolResult[PendingAction]: ...
    async def confirm_action(self, context: SessionContext, action_id: str) -> ToolResult[ConfirmResult]: ...
    async def get_cart(self, context: SessionContext) -> ToolResult[Cart]: ...
    async def get_pending_action(self, context: SessionContext) -> ToolResult[PendingActionResult]: ...


class ConditionsPort(Protocol):
    async def get_conditions(self, topic: str) -> ToolResult[ConditionsResult]: ...


__all__ = [name for name in globals() if not name.startswith("_")]
