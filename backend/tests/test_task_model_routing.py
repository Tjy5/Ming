import asyncio
import json
from types import SimpleNamespace

import ai.openai_provider as openai_provider_mod
import ai.z_provider as z_provider_mod
from ai.openai_provider import OpenAIProvider
from ai.z_provider import ZProvider
from models.enums import DecreeType
from models.game import StructuredDecree, create_initial_state


class _FakeCompletions:
    def __init__(self, model_to_content: dict[str, object]):
        self._model_to_content = model_to_content
        self.fail_models: set[str] = set()
        self.calls: list[str] = []
        self.extra_bodies: list[dict | None] = []
        self.call_kwargs: list[dict] = []

    async def create(
        self,
        *,
        model,
        messages,
        temperature,
        response_format=None,
        **kwargs,
    ):
        stream = bool(kwargs.pop("stream", False))
        self.calls.append(model)
        self.call_kwargs.append({
            "temperature": temperature,
            "response_format": response_format,
            "stream": stream,
            **kwargs,
        })
        self.extra_bodies.append(kwargs.get("extra_body"))
        if model in self.fail_models:
            raise RuntimeError(f"{model} unavailable")
        content = self._model_to_content.get(model, self._model_to_content.get("*", ""))
        if stream:
            if isinstance(content, list):
                stream_items = list(content)
            else:
                stream_items = [content]

            async def _stream():
                for item in stream_items:
                    if isinstance(item, Exception):
                        raise item
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=str(item)))]
                    )

            return _stream()

        if isinstance(content, list):
            content = "".join(str(chunk) for chunk in content)
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


def test_stream_narrative_uses_native_stream(monkeypatch):
    state = create_initial_state()
    completions = _FakeCompletions({
        "main-model": ["朕", "准", "此议。"],
    })
    _patch_openai_client(monkeypatch, openai_provider_mod, _FakeClient(completions))

    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")

    provider = OpenAIProvider()
    decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)

    async def _collect() -> list[str]:
        parts: list[str] = []
        async for chunk in provider.stream_narrative({}, state, [], decree):
            parts.append(chunk)
        return parts

    parts = asyncio.run(_collect())
    assert "".join(parts) == "朕准此议。"
    assert completions.calls == ["main-model"]
    assert completions.call_kwargs[0]["stream"] is True


def test_stream_narrative_partial_error_does_not_duplicate(monkeypatch):
    state = create_initial_state()
    completions = _FakeCompletions({
        "main-model": ["朕", RuntimeError("stream broken")],
    })
    _patch_openai_client(monkeypatch, openai_provider_mod, _FakeClient(completions))
    monkeypatch.setenv("OPENAI_MODEL_NAME", "main-model")

    provider = OpenAIProvider()
    decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)

    async def _collect() -> list[str]:
        parts: list[str] = []
        async for chunk in provider.stream_narrative({}, state, [], decree):
            parts.append(chunk)
        return parts

    parts = asyncio.run(_collect())
    assert parts == ["朕"]


def test_z_provider_defaults_to_main_model_for_parse_and_commentary(monkeypatch):
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

    assert provider.parse_model == "z-main-model"
    assert provider.turn_commentary_model == "z-main-model"
    assert provider.freeform_model == "z-main-model"


def test_z_provider_thinking_policy_defaults(monkeypatch):
    completions = _FakeCompletions({
        "z-main-model": json.dumps({"decrees": [{"type": "tax_increase"}]}),
    })
    fake_client = _FakeClient(completions)
    _patch_openai_client(monkeypatch, openai_provider_mod, fake_client)
    _patch_openai_client(monkeypatch, z_provider_mod, fake_client)

    monkeypatch.delenv("Z_ENABLE_THINKING_DEFAULT", raising=False)
    monkeypatch.delenv("Z_ENABLE_THINKING_TASKS", raising=False)
    monkeypatch.setenv("Z_MODEL", "z-main-model")

    provider = ZProvider()

    assert provider._chat_completion_extra_kwargs(
        task_name="parse_free_input",
        model=provider.model,
    ) == {"extra_body": {"enable_thinking": False}}
    assert provider._chat_completion_extra_kwargs(
        task_name="generate_memorial",
        model=provider.model,
    ) == {"extra_body": {"enable_thinking": True}}

    state = create_initial_state()
    result = asyncio.run(provider.parse_free_input("加税", state))

    assert isinstance(result, list)
    assert completions.extra_bodies == [{"enable_thinking": False}]


def test_z_provider_thinking_tasks_override(monkeypatch):
    fake_client = _FakeClient(_FakeCompletions({"*": "{}"}))
    _patch_openai_client(monkeypatch, openai_provider_mod, fake_client)
    _patch_openai_client(monkeypatch, z_provider_mod, fake_client)

    monkeypatch.setenv("Z_MODEL", "z-main-model")
    monkeypatch.setenv("Z_ENABLE_THINKING_TASKS", "process_freeform")

    provider = ZProvider()

    assert provider._chat_completion_extra_kwargs(
        task_name="generate_memorial",
        model=provider.model,
    ) == {"extra_body": {"enable_thinking": False}}
    assert provider._chat_completion_extra_kwargs(
        task_name="process_freeform",
        model=provider.model,
    ) == {"extra_body": {"enable_thinking": True}}


def test_z_provider_task_sampling_config_overrides(monkeypatch):
    completions = _FakeCompletions({
        "z-main-model": json.dumps({"decrees": [{"type": "tax_increase"}]}),
    })
    fake_client = _FakeClient(completions)
    _patch_openai_client(monkeypatch, openai_provider_mod, fake_client)
    _patch_openai_client(monkeypatch, z_provider_mod, fake_client)

    monkeypatch.setenv("Z_MODEL", "z-main-model")
    monkeypatch.setenv("Z_PARSE_FREE_INPUT_TEMPERATURE", "0.23")
    monkeypatch.setenv("Z_PARSE_FREE_INPUT_TOP_P", "0.91")

    provider = ZProvider()
    state = create_initial_state()
    result = asyncio.run(provider.parse_free_input("加税", state))

    assert isinstance(result, list)
    assert result[0].type == DecreeType.TAX_INCREASE
    assert completions.call_kwargs[0]["temperature"] == 0.23
    assert completions.call_kwargs[0]["top_p"] == 0.91


def test_z_provider_sampling_invalid_values_fall_back(monkeypatch):
    completions = _FakeCompletions({
        "z-main-model": json.dumps({"decrees": [{"type": "tax_increase"}]}),
    })
    fake_client = _FakeClient(completions)
    _patch_openai_client(monkeypatch, openai_provider_mod, fake_client)
    _patch_openai_client(monkeypatch, z_provider_mod, fake_client)

    monkeypatch.setenv("Z_MODEL", "z-main-model")
    monkeypatch.setenv("Z_PARSE_FREE_INPUT_TEMPERATURE", "9")
    monkeypatch.setenv("Z_PARSE_FREE_INPUT_TOP_P", "2")

    provider = ZProvider()
    state = create_initial_state()
    result = asyncio.run(provider.parse_free_input("加税", state))

    assert isinstance(result, list)
    assert result[0].type == DecreeType.TAX_INCREASE
    assert completions.call_kwargs[0]["temperature"] == 0.1
    assert "top_p" not in completions.call_kwargs[0]
