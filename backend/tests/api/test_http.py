import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_and_session_creation_do_not_require_llm():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/health")
            created = await client.post("/api/v1/sessions")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert created.status_code == 201
    assert set(created.json()) == {"session_id", "session_token"}


@pytest.mark.asyncio
async def test_chat_rejects_missing_or_invalid_bearer_with_contract_error():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            missing = await client.post("/api/v1/chat", json={"message": "hello"})
            invalid = await client.post("/api/v1/chat", headers={"Authorization": "Bearer wrong"}, json={"message": "hello"})

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "SESSION_INVALID"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
async def test_invalid_chat_body_is_not_exposed_as_fastapi_traceback():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session = await client.post("/api/v1/sessions")
            token = session.json()["session_token"]
            response = await client.post("/api/v1/chat", headers={"Authorization": f"Bearer {token}"}, json={"message": "   "})

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "INVALID_REQUEST", "message": "Request validation failed", "retryable": False}}
