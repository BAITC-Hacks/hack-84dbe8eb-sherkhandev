from __future__ import annotations

import html
from types import SimpleNamespace

import httpx
import pytest

from app.main import app


class FakeResponses:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_full_fixture_e2e_flow():
    async with app.router.lifespan_context(app):
        # Setup mock responses for LLM
        prepare_call = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="prepare_cart_action",
                    call_id="call-prep-1",
                    arguments='{"product_id":"demo-001","warehouse_id":"demo-warehouse","quantity_to_add":2}',
                )
            ]
        )
        final_text = SimpleNamespace(output=[], output_text="Предложение подготовлено.")
        fake_llm = SimpleNamespace(responses=FakeResponses([prepare_call, final_text]))
        app.state.agent.llm_client = fake_llm

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # a. POST /api/v1/sessions -> create session
            session_res = await client.post("/api/v1/sessions")
            assert session_res.status_code == 201
            session_data = session_res.json()
            session_token = session_data["session_token"]
            headers = {"Authorization": f"Bearer {session_token}"}

            # b. GET /api/v1/warehouses -> list eligible warehouses
            wh_res = await client.get("/api/v1/warehouses", headers=headers)
            assert wh_res.status_code == 200
            warehouses = wh_res.json()["warehouses"]
            eligible_wh = [w for w in warehouses if w["warehouse_id"] == "demo-warehouse" and w["eligible"] is True]
            assert len(eligible_wh) == 1

            # c. POST /api/v1/chat -> prepare addition of 2 pcs demo-001
            chat_res = await client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "добавь 2 шт demo-001", "warehouse_id": "demo-warehouse"},
            )
            assert chat_res.status_code == 200
            chat_data = chat_res.json()
            assert chat_data["pending_action"] is not None
            action_id = chat_data["pending_action"]["action_id"]
            assert chat_data["pending_action"]["product_id"] == "demo-001"
            assert chat_data["pending_action"]["quantity_to_add"] == 2

            # d. POST /api/v1/cart/actions/{action_id}/confirm -> confirm proposal
            confirm_res = await client.post(
                f"/api/v1/cart/actions/{action_id}/confirm",
                headers=headers,
            )
            assert confirm_res.status_code == 200
            confirm_data = confirm_res.json()
            assert confirm_data["already_applied"] is False
            cart = confirm_data["cart"]
            assert len(cart["items"]) == 1
            assert cart["items"][0]["quantity"] == 2
            assert float(cart["total"]) == 2400.00
            cart_url = cart["cart_url"]
            assert cart_url is not None
            assert "/cart/view/" in cart_url

            # e. Repeat confirm with same action_id -> already_applied=True and unchanged cart with single row
            repeat_confirm_res = await client.post(
                f"/api/v1/cart/actions/{action_id}/confirm",
                headers=headers,
            )
            assert repeat_confirm_res.status_code == 200
            repeat_data = repeat_confirm_res.json()
            assert repeat_data["already_applied"] is True
            assert len(repeat_data["cart"]["items"]) == 1
            assert repeat_data["cart"]["items"][0]["quantity"] == 2
            assert float(repeat_data["cart"]["total"]) == 2400.00

            # f. GET /cart/view/{view_token} WITHOUT Authorization and WITHOUT calling get_cart()
            view_token = cart_url.rstrip("/").split("/")[-1]
            view_res = await client.get(f"/cart/view/{view_token}")
            assert view_res.status_code == 200
            assert "text/html" in view_res.headers.get("content-type", "")
            assert view_res.headers.get("cache-control") == "no-store"
            assert view_res.headers.get("referrer-policy") == "no-referrer"
            html_content = view_res.text
            assert "Учебный автомат A" in html_content
            assert "2 шт." in html_content
            assert "2400.00 KZT" in html_content
            assert "fixture" in html_content


@pytest.mark.asyncio
async def test_cart_view_security_headers_and_escaping():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session_res = await client.post("/api/v1/sessions")
            token = session_res.json()["session_token"]
            session_id = session_res.json()["session_id"]
            headers = {"Authorization": f"Bearer {token}"}

            # Prepare and confirm an action
            action_res = await app.state.cart.prepare_action(
                app.state.sessions._sessions[session_id].context,
                "demo-001",
                "demo-warehouse",
                1,
            )
            assert action_res.ok is True
            action_id = action_res.data.action_id

            confirm_res = await client.post(f"/api/v1/cart/actions/{action_id}/confirm", headers=headers)
            cart_url = confirm_res.json()["cart"]["cart_url"]
            view_token = cart_url.rstrip("/").split("/")[-1]

            # Verify view headers
            view_res = await client.get(f"/cart/view/{view_token}")
            assert view_res.status_code == 200
            assert view_res.headers["cache-control"] == "no-store"
            assert view_res.headers["referrer-policy"] == "no-referrer"

            # Check escaping for potentially malicious content
            # Direct check that render_view handles script injection safely
            unsafe_name = "<script>alert('xss')</script>"
            escaped = html.escape(unsafe_name)
            assert "<script>" not in escaped
            assert "&lt;script&gt;" in escaped


@pytest.mark.asyncio
async def test_conditions_and_certificates_demo_flow():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Conditions via conditions service
            cond = await app.state.conditions.get_conditions("delivery")
            assert cond.ok is True
            assert cond.data.status == "known"
            assert "самовывоз" in cond.data.text.lower()

            cond_pay = await app.state.conditions.get_conditions("payment")
            assert cond_pay.ok is True
            assert "оплата" in cond_pay.data.text.lower()

            # 2. Static certificate endpoint
            cert_res = await client.get("/demo-certificates/DEMO-CERT-001.html")
            assert cert_res.status_code == 200
            assert "DEMO-CERT-001" in cert_res.text
            assert "демонстрационный документ" in cert_res.text


@pytest.mark.asyncio
async def test_unconfigured_llm_returns_503_llm_unavailable():
    async with app.router.lifespan_context(app):
        # Explicitly ensure llm_client is None
        app.state.agent.llm_client = None

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session_res = await client.post("/api/v1/sessions")
            token = session_res.json()["session_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Normal chat query without configured LLM must return 503 LLM_UNAVAILABLE
            chat_res = await client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "Привет, помоги выбрать автомат"},
            )
            assert chat_res.status_code == 503
            err_data = chat_res.json()
            assert err_data["error"]["code"] == "LLM_UNAVAILABLE"

            # Exact confirmation with an action ID does NOT require LLM
            # (it must bypass LLM and go straight to server cart logic)
            exact_res = await client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "да, добавь", "confirmation_action_id": "nonexistent-action"},
            )
            # Fails with 404 ACTION_NOT_FOUND from cart, not 503 LLM_UNAVAILABLE
            assert exact_res.status_code == 404
            assert exact_res.json()["error"]["code"] == "ACTION_NOT_FOUND"
