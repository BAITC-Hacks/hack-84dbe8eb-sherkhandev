import pytest

from app.sessions import SessionStore


@pytest.mark.asyncio
async def test_session_token_is_not_session_id_and_bearer_is_required():
    store = SessionStore()
    created = await store.create()

    assert created.session_token != created.session_id
    context = await store.authenticate(created.session_token)
    assert context.session_id == created.session_id
    assert await store.authenticate(created.session_id) is None
    assert await store.authenticate("not-a-token") is None


@pytest.mark.asyncio
async def test_session_lock_is_shared_for_same_session():
    store = SessionStore()
    created = await store.create()
    first = await store.authenticate(created.session_token)
    second = await store.authenticate(created.session_token)

    assert first is not None and second is not None
    assert await store.get_lock(first.session_id) is await store.get_lock(second.session_id)

