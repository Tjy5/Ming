import asyncio

import pytest
from fastapi import HTTPException

import ai.provider as provider_mod
from ai.provider import (
    AIProvider,
    PARSE_ERROR_TYPE_UNAVAILABLE,
    ResilientProvider,
    _is_non_retryable_portrait_error,
)
from api import routes
from models.game import DebateResult, GameState, Minister, StructuredDecree, create_initial_state


class _BaseProvider(AIProvider):
    async def generate_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ) -> str:
        return ""

    async def stream_narrative(
        self,
        delta_attribution: dict,
        game_state: GameState,
        chain_events: list[str],
        decree: StructuredDecree,
    ):
        narrative = await self.generate_narrative(
            delta_attribution,
            game_state,
            chain_events,
            decree,
        )
        if narrative:
            yield narrative

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

    async def generate_portrait(self, minister_name: str, description: str) -> str | None:
        return None

    async def generate_memorial(self, trigger_reason, author, game_state):
        return ""

    async def generate_minister_reaction(self, minister, decree, stance, game_state):
        return ""

    async def generate_assembly_debate(self, topic, participants, game_state):
        return None

    async def generate_turn_commentary(self, summary_data, game_state):
        return ""

    async def generate_minister_dialogue(self, *a, **kw):
        return {}

    async def process_freeform(self, text, game_state, *, script_context=None):
        return {"error": "not implemented"}


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


class _SlowCommentaryProvider(_BaseProvider):
    def __init__(self):
        self.calls = 0

    async def generate_turn_commentary(self, summary_data, game_state):
        self.calls += 1
        await asyncio.sleep(0.2)
        return "slow ai commentary"


class _SlowParseProvider(_BaseProvider):
    def __init__(self):
        self.calls = 0

    async def parse_free_input(self, text: str, game_state: GameState):
        self.calls += 1
        await asyncio.sleep(0.2)
        return []


class _SlowFreeformProvider(_BaseProvider):
    def __init__(self):
        self.calls = 0

    async def process_freeform(self, text, game_state, *, script_context=None):
        self.calls += 1
        await asyncio.sleep(0.2)
        return {"error": "slow"}


class _HangingStreamProvider(_BaseProvider):
    async def stream_narrative(self, *args, **kwargs):
        await asyncio.sleep(0.2)
        if False:
            yield ""


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


def test_turn_commentary_has_dedicated_timeout_and_retry():
    inner = _SlowCommentaryProvider()
    provider = ResilientProvider(
        inner,
        timeout=1,
        retries=3,
        turn_commentary_timeout=0.01,
        turn_commentary_retries=1,
    )
    state = create_initial_state()

    result = asyncio.run(provider.generate_turn_commentary({"major_events": ["测试事件"]}, state))

    assert "朝政动荡，1件大事需关注" in result
    assert inner.calls == 1


def test_turn_commentary_retry_log_includes_exception_type(caplog):
    inner = _SlowCommentaryProvider()
    provider = ResilientProvider(
        inner,
        timeout=1,
        retries=3,
        turn_commentary_timeout=0.01,
        turn_commentary_retries=1,
    )
    state = create_initial_state()

    with caplog.at_level("ERROR"):
        asyncio.run(provider.generate_turn_commentary({"major_events": ["测试事件"]}, state))

    assert any(
        "generate_turn_commentary attempt 1/1 failed (TimeoutError)" in rec.message
        for rec in caplog.records
    )


def test_parse_has_dedicated_timeout_and_retry(monkeypatch):
    monkeypatch.setattr(provider_mod, "_rule_parse_fallback_enabled", False)
    inner = _SlowParseProvider()
    provider = ResilientProvider(
        inner,
        timeout=1,
        retries=3,
        parse_timeout=0.01,
        parse_retries=1,
    )
    state = create_initial_state()

    result = asyncio.run(provider.parse_free_input("加税", state))

    assert isinstance(result, dict)
    assert result.get("error_type") == PARSE_ERROR_TYPE_UNAVAILABLE
    assert inner.calls == 1


def test_freeform_has_dedicated_timeout_and_retry():
    inner = _SlowFreeformProvider()
    provider = ResilientProvider(
        inner,
        timeout=1,
        retries=3,
        freeform_timeout=0.01,
        freeform_retries=1,
    )
    state = create_initial_state()

    result = asyncio.run(provider.process_freeform("加税", state))

    assert isinstance(result, dict)
    assert result.get("error_type") == PARSE_ERROR_TYPE_UNAVAILABLE
    assert inner.calls == 1


def test_stream_narrative_has_timeout_and_fallback():
    inner = _HangingStreamProvider()
    provider = ResilientProvider(
        inner,
        timeout=0.01,
        retries=1,
    )
    state = create_initial_state()
    decree = StructuredDecree(type="harsh_punishment")

    async def _collect():
        chunks: list[str] = []
        async for chunk in provider.stream_narrative({}, state, [], decree):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(_collect())
    assert result == ["（AI服务响应异常，但政令已执行）"]
