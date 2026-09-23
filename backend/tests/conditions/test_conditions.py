from __future__ import annotations

from pathlib import Path

import pytest

from app.conditions import ConditionsService


DATA = Path(__file__).resolve().parents[2] / "data" / "conditions"


@pytest.mark.asyncio
async def test_all_fixture_topics_are_explicitly_demonstrational():
    service = ConditionsService(DATA, "fixture")
    await service.initialize()
    for topic in ("payment", "delivery", "minimum_order"):
        result = await service.get_conditions(topic)
        assert result.ok
        assert "демонстрационные условия" in result.data.text.lower()
        assert result.data.source_kind == "synthetic"
    await service.close()


@pytest.mark.asyncio
async def test_live_unknown_is_not_replaced_with_fixture():
    service = ConditionsService(DATA, "live")
    result = await service.get_conditions("payment")
    assert result.ok
    assert result.data.status == "unknown"
    assert result.data.text is None
    assert result.data.source_kind == "ekt"


@pytest.mark.asyncio
async def test_unknown_topic_is_invalid_request():
    service = ConditionsService(DATA, "fixture")
    result = await service.get_conditions("shipping_discount")
    assert not result.ok
    assert result.error.code == "INVALID_REQUEST"
