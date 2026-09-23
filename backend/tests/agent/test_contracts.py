from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts import (
    ChatRequest,
    ErrorInfo,
    PendingAction,
    ToolResult,
)


def test_chat_request_rejects_empty_or_extra_fields():
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")

    with pytest.raises(ValidationError):
        ChatRequest(message="hi", session_id="model-controlled")


def test_pending_action_rejects_non_integral_or_non_positive_quantity():
    payload = dict(
        action_id="a1",
        product_id="p1",
        warehouse_id="w1",
        product_name="Demo",
        quantity_to_add=0,
        unit_price="1.00",
        added_amount="0.00",
        currency="KZT",
        unit="pcs",
        quantity_step="1",
        stock_quantity="2",
        checked_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-01T00:05:00Z",
        status="pending",
        source_kind="synthetic",
    )
    with pytest.raises(ValidationError):
        PendingAction(**payload)

    payload["quantity_to_add"] = 1.5
    with pytest.raises(ValidationError):
        PendingAction(**payload)


def test_tool_result_has_exactly_one_payload_side():
    ok = ToolResult[dict](ok=True, data={"value": 1})
    assert ok.data == {"value": 1}
    assert ok.error is None

    with pytest.raises(ValidationError):
        ToolResult[dict](ok=True, data={}, error=ErrorInfo(code="X", message="bad", retryable=False))

    with pytest.raises(ValidationError):
        ToolResult[dict](ok=False, data={})

