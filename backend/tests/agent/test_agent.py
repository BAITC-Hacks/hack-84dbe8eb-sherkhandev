from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agent import AgentError, AgentService
from app.config import Settings
from app.contracts import (
    Cart,
    CartItem,
    CertificateResult,
    ConditionsResult,
    Product,
    SearchFilters,
    SearchResult,
    SessionContext,
    StockResult,
    ToolResult,
    Warehouse,
    WarehouseList,
)
from app.sessions import SessionStore


NOW = datetime.now(timezone.utc)


def product(product_id="p1"):
    return Product(
        product_id=product_id,
        article="P-1",
        name="Учебный автомат",
        price="1200.00",
        specs={"poles": "1"},
        certificate_urls=[],
        data_issues=[],
        source_kind="synthetic",
        fetched_at=NOW,
        unit="pcs",
        quantity_step="1",
    )


class FakeCatalog:
    def __init__(self):
        self.calls = []

    async def list_warehouses(self):
        self.calls.append(("list_warehouses",))
        return ToolResult(ok=True, data=WarehouseList(warehouses=[Warehouse(warehouse_id="w1", name="Учебный склад", eligible=True)]))

    async def search_products(self, query, filters, limit=5):
        self.calls.append(("search_products", query, filters, limit))
        return ToolResult(ok=True, data=SearchResult(products=[product()], warnings=[]))

    async def get_product(self, product_id, refresh=False):
        return ToolResult(ok=True, data=product(product_id))

    async def check_stock(self, product_id, warehouse_id, refresh=False):
        return ToolResult(ok=True, data=StockResult(product_id=product_id, warehouse_id=warehouse_id, warehouse_name="Учебный склад", quantity="3", warehouse_eligible=True, fetched_at=NOW, source_kind="synthetic", source_mode="fixture"))

    async def get_snapshot(self, product_id, warehouse_id, refresh=False):
        raise NotImplementedError

    async def find_analogs(self, product_id, warehouse_id, limit=3):
        raise NotImplementedError

    async def get_certificate(self, product_id):
        return ToolResult(ok=True, data=CertificateResult(product_id=product_id, urls=[], status="not_found_in_available_data"))


class FakeConditions:
    async def get_conditions(self, topic):
        return ToolResult(ok=True, data=ConditionsResult(topic=topic, text="Условия", source_urls=[], status="known", source_kind="synthetic"))


class FakeCart:
    def __init__(self):
        self.confirmed = []
        self.cart = Cart(cart_id="c1", items=[], total="0.00", data_mode="fixture", cart_url="https://example.test/cart/view/secret")

    async def prepare_action(self, context, product_id, warehouse_id, quantity_to_add):
        from app.contracts import PendingAction

        return ToolResult(ok=True, data=PendingAction(action_id="a1", product_id=product_id, warehouse_id=warehouse_id, product_name="Учебный автомат", quantity_to_add=quantity_to_add, unit_price="1200.00", added_amount=str(1200 * quantity_to_add), unit="pcs", quantity_step="1", stock_quantity="3", checked_at=NOW, expires_at=NOW + timedelta(minutes=5), source_kind="synthetic"))

    async def confirm_action(self, context, action_id):
        self.confirmed.append(action_id)
        from app.contracts import ConfirmResult

        return ToolResult(ok=True, data=ConfirmResult(action_id=action_id, already_applied=False, cart=self.cart))

    async def get_cart(self, context):
        return ToolResult(ok=True, data=self.cart)

    async def get_pending_action(self, context):
        raise NotImplementedError


class FakeResponses:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def service(responses, *, cart=None):
    sessions = SessionStore()
    catalog = FakeCatalog()
    fake_cart = cart or FakeCart()
    fake_llm = SimpleNamespace(responses=FakeResponses(responses))
    agent = AgentService(fake_llm, catalog, fake_cart, FakeConditions(), sessions, Settings())
    return agent, sessions, catalog, fake_cart, fake_llm.responses


@pytest.mark.asyncio
async def test_agent_executes_only_registered_tool_with_valid_arguments():
    responses = [
        SimpleNamespace(output=[SimpleNamespace(type="function_call", name="search_products", call_id="call-1", arguments='{"query":"автомат","filters":{"category":null,"brand":null,"specs":[]},"limit":5}')]),
        SimpleNamespace(output=[], output_text="Нашёл товар."),
    ]
    agent, sessions, catalog, _, llm = service(responses)
    created = await sessions.create()

    result = await agent.handle_message(SessionContext(session_id=created.session_id), __import__("app.contracts", fromlist=["ChatRequest"]).ChatRequest(message="найди автомат"))

    assert result.products[0].product_id == "p1"
    assert catalog.calls[0][0] == "search_products"
    assert llm.calls[0]["tools"]
    assert all(item["name"] != "confirm_action" for item in llm.calls[0]["tools"])


@pytest.mark.asyncio
async def test_exact_confirmation_with_action_id_skips_llm_and_returns_server_cart():
    agent, sessions, _, cart, llm = service([])
    created = await sessions.create()
    result = await agent.handle_message(
        SessionContext(session_id=created.session_id),
        __import__("app.contracts", fromlist=["ChatRequest"]).ChatRequest(message="да, добавь", confirmation_action_id="a1"),
    )

    assert result.cart is cart.cart
    assert cart.confirmed == ["a1"]
    assert llm.calls == []
    assert "secret" not in AgentService.serialize_for_model(cart.cart)


@pytest.mark.asyncio
async def test_prepare_uses_server_values_and_rejects_unknown_tool():
    responses = [
        SimpleNamespace(output=[SimpleNamespace(type="function_call", name="prepare_cart_action", call_id="call-1", arguments='{"product_id":"p1","warehouse_id":"w1","quantity_to_add":2}')]),
        SimpleNamespace(output=[], output_text="неправильная цена 1"),
    ]
    agent, sessions, _, _, _ = service(responses)
    created = await sessions.create()

    result = await agent.handle_message(SessionContext(session_id=created.session_id), __import__("app.contracts", fromlist=["ChatRequest"]).ChatRequest(message="добавь два"))

    assert "2400.00" in result.message
    assert "неправильная цена" not in result.message


@pytest.mark.asyncio
async def test_invalid_tool_arguments_cannot_become_successful_addition():
    responses = [
        SimpleNamespace(output=[SimpleNamespace(type="function_call", name="prepare_cart_action", call_id="call-1", arguments='{"product_id":"p1","warehouse_id":"w1","quantity_to_add":true,"extra":"ignored"}')]),
        SimpleNamespace(output=[], output_text="Добавлено успешно."),
    ]
    agent, sessions, _, _, _ = service(responses)
    created = await sessions.create()

    result = await agent.handle_message(SessionContext(session_id=created.session_id), __import__("app.contracts", fromlist=["ChatRequest"]).ChatRequest(message="добавь"))

    assert result.cart is None
    assert result.pending_action is None
    assert result.warnings == ["INVALID_REQUEST"]
    assert "подтверждённые данные" in result.message


@pytest.mark.asyncio
async def test_confirmation_phrase_without_action_id_does_not_change_cart():
    responses = [SimpleNamespace(output=[], output_text="Уточните идентификатор предложения.")]
    agent, sessions, _, cart, llm = service(responses)
    created = await sessions.create()

    result = await agent.handle_message(SessionContext(session_id=created.session_id), __import__("app.contracts", fromlist=["ChatRequest"]).ChatRequest(message="да, добавь"))

    assert cart.confirmed == []
    assert llm.calls
    assert result.message == "Уточните идентификатор предложения."


@pytest.mark.asyncio
async def test_session_context_warehouse_and_product_injected_into_safe_input():
    responses = [SimpleNamespace(output=[], output_text="Товар и склад учтены.")]
    agent, sessions, _, _, llm = service(responses)
    created = await sessions.create()
    await sessions.set_selection(created.session_id, warehouse_id="w-demo-1", product_id="prod-99")

    from app.contracts import ChatRequest
    result = await agent.handle_message(
        SessionContext(session_id=created.session_id),
        ChatRequest(message="какой склад выбран?"),
    )

    assert result.message == "Товар и склад учтены."
    assert len(llm.calls) == 1
    input_items = llm.calls[0]["input"]
    system_messages = [item for item in input_items if item.get("role") == "system"]
    assert any("Текущий подтверждённый склад: w-demo-1." in m.get("content", "") for m in system_messages)
    assert any("Текущий фокусный товар: prod-99." in m.get("content", "") for m in system_messages)
    # Ensure tokens are not leaked into LLM input
    assert not any(created.session_id in str(item) for item in input_items)


@pytest.mark.asyncio
async def test_session_context_empty_when_no_selection():
    responses = [SimpleNamespace(output=[], output_text="Ответ.")]
    agent, sessions, _, _, llm = service(responses)
    created = await sessions.create()

    from app.contracts import ChatRequest
    await agent.handle_message(
        SessionContext(session_id=created.session_id),
        ChatRequest(message="привет"),
    )

    input_items = llm.calls[0]["input"]
    system_messages = [item for item in input_items if item.get("role") == "system"]
    assert not any("Текущий подтверждённый склад:" in m.get("content", "") for m in system_messages)
    assert not any("Текущий фокусный товар:" in m.get("content", "") for m in system_messages)


def test_safe_text_sanitizes_cart_urls_and_tokens_and_preserves_certificates():
    # 1. Relative cart URL
    assert AgentService._safe_text("Ссылка: /cart/view/abc-123_xyz") == "Ссылка: [cart-link-redacted]"

    # 2. Absolute HTTP cart URL
    assert AgentService._safe_text("Ссылка: http://localhost:8000/cart/view/token123") == "Ссылка: [cart-link-redacted]"

    # 3. Absolute HTTPS cart URL
    assert AgentService._safe_text("Ссылка: https://store.ekt.kz/cart/view/token123") == "Ссылка: [cart-link-redacted]"

    # 4. Cart URL with query parameters
    assert AgentService._safe_text("Ссылка: /cart/view/xyz?token=123&mode=demo") == "Ссылка: [cart-link-redacted]"

    # 5. Cart URL with fragment
    assert AgentService._safe_text("Ссылка: /cart/view/xyz#summary") == "Ссылка: [cart-link-redacted]"

    # 6. Cart URL with query and fragment
    assert AgentService._safe_text("Ссылка: https://site.org/cart/view/xyz?token=123#summary") == "Ссылка: [cart-link-redacted]"

    # 7. Bearer token in various casing
    assert AgentService._safe_text("Header: Bearer sec.ret-123_xyz~") == "Header: Bearer [token-redacted]"
    assert AgentService._safe_text("Header: bearer sec.ret-123_xyz~") == "Header: Bearer [token-redacted]"
    assert AgentService._safe_text("Header: BEARER sec.ret-123_xyz~") == "Header: Bearer [token-redacted]"

    # 8. Certificate links preserved and untouched
    cert_relative = "Сертификат: /demo-certificates/demo-001.pdf"
    assert AgentService._safe_text(cert_relative) == cert_relative

    cert_absolute = "Сертификат: https://example.com/demo-certificates/demo-001.pdf"
    assert AgentService._safe_text(cert_absolute) == cert_absolute

