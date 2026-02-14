import asyncio

import pytest
from fastapi import HTTPException

from ai.provider import AIProvider, ResilientProvider, _is_non_retryable_portrait_error
from api import routes
from models.game import DebateResult, GameState, Minister, StructuredDecree


class _BaseProvider(AIProvider):
    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> str:
        return ""

    async def parse_free_input(
        self,
        text: str,
        game_state: GameState,
    ) -> list[StructuredDecree] | dict:
        return []

    async def rejection_narrative(self, decree: StructuredDecree, reason: str) -> str:
        return ""

    async def generate_debate_narrative(
        self,
        topic: str,
        minister_a: Minister,
        minister_b: Minister,
        game_state: GameState,
    ) -> DebateResult | None:
        return None


class _AlwaysRaisePortraitProvider(_BaseProvider):
    def __init__(self):
        self.calls = 0

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        self.calls += 1
        raise RuntimeError("model_not_found")


class _AlwaysNonePortraitProvider(_BaseProvider):
    def __init__(self):
        self.calls = 0

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        self.calls += 1
        return None


def test_non_retryable_portrait_error_detection():
    assert _is_non_retryable_portrait_error(RuntimeError("model_not_found"))
    assert _is_non_retryable_portrait_error(RuntimeError("429 too many requests"))
    assert not _is_non_retryable_portrait_error(RuntimeError("temporary timeout"))


def test_resilient_provider_stops_retry_on_non_retryable_error():
    inner = _AlwaysRaisePortraitProvider()
    provider = ResilientProvider(inner, retries=3)

    result = asyncio.run(provider.generate_portrait("魏忠贤", "明朝官员"))

    assert result is None
    assert inner.calls == 1


def test_portrait_endpoint_cools_down_after_failure():
    inner = _AlwaysNonePortraitProvider()
    provider = ResilientProvider(inner, retries=1)
    req = routes.PortraitRequest(minister_name="徐光启", description="明朝官员")

    old_provider = routes._provider
    old_cooldown = routes._portrait_cooldown_until
    try:
        routes._provider = provider
        routes._portrait_cooldown_until = 0.0

        with pytest.raises(HTTPException) as first:
            asyncio.run(routes.create_portrait(req))
        assert first.value.status_code == 503
        assert first.value.detail["error_code"] == "portrait_generation_failed"
        first_calls = inner.calls
        assert first_calls == 1

        with pytest.raises(HTTPException) as second:
            asyncio.run(routes.create_portrait(req))
        assert second.value.status_code == 503
        assert second.value.detail["error_code"] == "portrait_generation_cooldown"
        assert inner.calls == first_calls
    finally:
        routes._provider = old_provider
        routes._portrait_cooldown_until = old_cooldown
