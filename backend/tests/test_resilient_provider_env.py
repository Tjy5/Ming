import asyncio

import pytest

from ai.provider import MockProvider, ResilientProvider
from models.game import create_initial_state


def test_resilient_provider_reads_global_timeout_retry_from_env(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT", "12")
    monkeypatch.setenv("AI_RETRIES", "4")

    provider = ResilientProvider(MockProvider())

    assert provider._timeout == 12.0
    assert provider._retries == 4


def test_resilient_provider_explicit_timeout_retry_override_env(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT", "12")
    monkeypatch.setenv("AI_RETRIES", "4")

    provider = ResilientProvider(MockProvider(), timeout=1.5, retries=1)

    assert provider._timeout == 1.5
    assert provider._retries == 1


class _FailDialogueProvider(MockProvider):
    async def generate_minister_dialogue(self, *args, **kwargs):
        raise RuntimeError("dialogue failed")


def test_resilient_provider_dialogue_raises_when_mock_provider_disabled(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("AI_ENABLE_MOCK_FALLBACK", raising=False)

    provider = ResilientProvider(_FailDialogueProvider(), timeout=1, retries=1)
    state = create_initial_state()
    minister = next(m for m in state.ministers if m.status.value == "active")

    with pytest.raises(RuntimeError, match="dialogue failed"):
        asyncio.run(
            provider.generate_minister_dialogue(
                minister=minister,
                message="测试",
                game_state=state,
                conversation_history=[],
            )
        )


def test_resilient_provider_dialogue_uses_mock_fallback_when_provider_is_mock(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.delenv("AI_ENABLE_MOCK_FALLBACK", raising=False)

    provider = ResilientProvider(_FailDialogueProvider(), timeout=1, retries=1)
    state = create_initial_state()
    minister = next(m for m in state.ministers if m.status.value == "active")

    result = asyncio.run(
        provider.generate_minister_dialogue(
            minister=minister,
            message="测试",
            game_state=state,
            conversation_history=[],
        )
    )

    assert isinstance(result, dict)
    assert "reply" in result
