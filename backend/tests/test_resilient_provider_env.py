import asyncio

import pytest

from ai.provider import ResilientProvider
from fakes import FakeProvider
from models.enums import MinisterStatus
from models.game import create_initial_state


def test_resilient_provider_reads_global_timeout_retry_from_env(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT", "12")
    monkeypatch.setenv("AI_RETRIES", "4")

    provider = ResilientProvider(FakeProvider())

    assert provider._timeout == 12.0
    assert provider._retries == 4


def test_resilient_provider_explicit_timeout_retry_override_env(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT", "12")
    monkeypatch.setenv("AI_RETRIES", "4")

    provider = ResilientProvider(FakeProvider(), timeout=1.5, retries=1)

    assert provider._timeout == 1.5
    assert provider._retries == 1


class _FailDialogueProvider(FakeProvider):
    async def generate_minister_dialogue(self, *args, **kwargs):
        raise RuntimeError("dialogue failed")


def test_resilient_provider_dialogue_raises_after_retries(monkeypatch):
    # 无 mock 回退：配置的真实 provider 失败后必须抛错，由调用方展示配置错误。
    provider = ResilientProvider(_FailDialogueProvider(), timeout=1, retries=1)
    state = create_initial_state()
    # 新档开局 1328-10 大臣均未入仕，显式激活一名
    state.ministers[0].status = MinisterStatus.ACTIVE
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
