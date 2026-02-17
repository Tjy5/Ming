import asyncio
import json
from types import SimpleNamespace

import ai.openai_provider as openai_provider_mod
import ai.z_provider as z_provider_mod
from ai.openai_provider import OpenAIProvider
from ai.z_provider import ZProvider
from models.enums import DecreeType
from models.game import create_initial_state


class _FakeCompletions:
    def __init__(self, model_to_content: dict[str, str]):
        self._model_to_content = model_to_content
        self.fail_models: set[str] = set()
        self.calls: list[str] = []

    async def create(
        self,
        *,
        model,
        messages,
        temperature,
        response_format=None,
    ):
        self.calls.append(model)
        if model in self.fail_models:
            raise RuntimeError(f"{model} unavailable")
        content = self._model_to_content.get(model, self._model_to_content.get("*", ""))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


def _patch_openai_client(monkeypatch, module, fake_client: _FakeClient) -> None:
    monkeypatch.setattr(module.openai, "AsyncOpenAI", lambda **kwargs: fake_client)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: object())


def test_parse_free_input_falls_back_to_primary_model(monkeypatch):
    state = create_initial_state()
    completions = _FakeCompletions({
        "main-model": json.dumps({"decrees": [{"type": "tax_increase"}]}),
    })
    completions.fail_models.add("flash-model")
    _patch_openai_client(monkeypatch, openai_provider_mod, _FakeClient(completions))

    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")
    monkeypatch.setenv("OPENAI_SIMPLE_MODEL", "flash-model")

    provider = OpenAIProvider()
    result = asyncio.run(provider.parse_free_input("加税", state))

    assert isinstance(result, list)
    assert result[0].type == DecreeType.TAX_INCREASE
    assert completions.calls == ["flash-model", "main-model"]


def test_turn_commentary_prefers_simple_model(monkeypatch):
    state = create_initial_state()
    completions = _FakeCompletions({
        "flash-model": "本月朝政小结。",
    })
    _patch_openai_client(monkeypatch, openai_provider_mod, _FakeClient(completions))

    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")
    monkeypatch.setenv("OPENAI_SIMPLE_MODEL", "flash-model")

    provider = OpenAIProvider()
    result = asyncio.run(provider.generate_turn_commentary({"major_events": []}, state))

    assert result == "本月朝政小结。"
    assert completions.calls == ["flash-model"]


def test_z_provider_defaults_flash_for_parse_and_commentary(monkeypatch):
    fake_client = _FakeClient(_FakeCompletions({"*": "{}"}))
    _patch_openai_client(monkeypatch, openai_provider_mod, fake_client)
    _patch_openai_client(monkeypatch, z_provider_mod, fake_client)

    monkeypatch.delenv("OPENAI_SIMPLE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_PARSE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_FREEFORM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_TURN_COMMENTARY_MODEL", raising=False)
    monkeypatch.delenv("Z_SIMPLE_MODEL", raising=False)
    monkeypatch.delenv("Z_PARSE_MODEL", raising=False)
    monkeypatch.delenv("Z_FREEFORM_MODEL", raising=False)
    monkeypatch.delenv("Z_TURN_COMMENTARY_MODEL", raising=False)
    monkeypatch.setenv("Z_MODEL", "z-main-model")

    provider = ZProvider()

    assert provider.parse_model == "qwen3-omni-flash-2025-12-01"
    assert provider.turn_commentary_model == "qwen3-omni-flash-2025-12-01"
    assert provider.freeform_model == "z-main-model"
