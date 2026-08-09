from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from ai.base import GenerationResult
from ai.anthropic_provider import AnthropicProvider
from ai.config import normalize_ai_config
from ai.factory import SINGLE_ATTEMPT, build_provider
from ai.google_provider import GoogleProvider
from ai.h_provider import HProvider
from ai.openai_provider import OpenAIProvider
from ai.openai_response_provider import OpenAIResponseProvider
from ai.resilient import ResilientProvider
from ai.z_provider import ZProvider
from fakes import FakeProvider


class _CountingProvider(FakeProvider):
    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail

    async def generate_text_once(self, *args, **kwargs) -> GenerationResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("secret response body")
        return GenerationResult(text="OK")


@pytest.mark.parametrize("fail", [False, True])
def test_resilient_probe_never_retries_or_falls_back(fail):
    inner = _CountingProvider(fail=fail)
    provider = ResilientProvider(inner, timeout=1, retries=7)

    async def run():
        if fail:
            with pytest.raises(RuntimeError):
                await provider.probe_generation_once()
        else:
            result = await provider.probe_generation_once()
            assert result.text == "OK"

    asyncio.run(run())
    assert inner.calls == 1


class _FakeCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            _request_id="provider_req_safe",
        )


class _FakeOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())
        self.closed = False

    async def close(self):
        self.closed = True


def test_openai_probe_uses_main_model_and_thinking_exactly_once(monkeypatch):
    fake = _FakeOpenAIClient()
    captured: dict = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("ai.openai_provider.openai.AsyncOpenAI", create_client)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    provider = OpenAIProvider(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        enable_thinking=True,
        thinking_config={"reasoning_effort": "low"},
        http_client=client,
        sdk_max_retries=0,
        use_environment=False,
    )

    result = asyncio.run(provider.probe_generation_once())

    assert result.text == "OK"
    assert len(fake.chat.completions.calls) == 1
    call = fake.chat.completions.calls[0]
    assert call["model"] == "main-model"
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] == 8
    assert captured["max_retries"] == 0
    asyncio.run(provider.aclose())
    assert fake.closed is True


class _FakeGoogleModels:
    def __init__(self):
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            text="OK",
            usage_metadata=SimpleNamespace(
                prompt_token_count=3,
                candidates_token_count=1,
            ),
        )


class _FakeGoogleAio:
    def __init__(self):
        self.models = _FakeGoogleModels()
        self.closed = False

    async def aclose(self):
        self.closed = True


def test_google_probe_uses_main_model_thinking_and_one_sdk_attempt(monkeypatch):
    fake = SimpleNamespace(aio=_FakeGoogleAio())
    captured: dict = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("ai.google_provider.genai.Client", create_client)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200)),
    )
    provider = GoogleProvider(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        thinking_config={"thinkingLevel": "LOW"},
        http_client=http_client,
        sdk_max_retries=0,
        use_environment=False,
    )

    result = asyncio.run(provider.probe_generation_once())

    assert result.text == "OK"
    assert len(fake.aio.models.calls) == 1
    call = fake.aio.models.calls[0]
    assert call["model"] == "main-model"
    assert "LOW" in str(call["config"].thinking_config).upper()
    assert captured["http_options"].retry_options.attempts == 1
    asyncio.run(provider.aclose())
    asyncio.run(http_client.aclose())
    assert fake.aio.closed is True


class _FakeAnthropicMessages:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="OK")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
            _request_id="provider_req_safe",
        )


class _FakeAnthropicClient:
    def __init__(self):
        self.messages = _FakeAnthropicMessages()
        self.closed = False

    async def close(self):
        self.closed = True


def test_anthropic_probe_uses_main_model_thinking_and_zero_sdk_retries(monkeypatch):
    fake = _FakeAnthropicClient()
    captured: dict = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("ai.anthropic_provider.AsyncAnthropic", create_client)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200)),
    )
    provider = AnthropicProvider(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        thinking_config={"type": "enabled", "budget_tokens": 128},
        http_client=http_client,
        sdk_max_retries=0,
        use_environment=False,
    )

    result = asyncio.run(provider.probe_generation_once())

    assert result.text == "OK"
    assert len(fake.messages.calls) == 1
    call = fake.messages.calls[0]
    assert call["model"] == "main-model"
    assert call["max_tokens"] == 8
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 128}
    assert captured["max_retries"] == 0
    assert captured["http_client"] is http_client
    asyncio.run(provider.aclose())
    asyncio.run(http_client.aclose())
    assert fake.closed is True


def test_responses_probe_uses_main_model_thinking_and_one_http_call(monkeypatch):
    fake_sdk = _FakeOpenAIClient()
    captured_sdk: dict = {}
    requests: list[httpx.Request] = []

    def create_client(**kwargs):
        captured_sdk.update(kwargs)
        return fake_sdk

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"output_text": "OK"})

    monkeypatch.setattr("ai.openai_provider.openai.AsyncOpenAI", create_client)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenAIResponseProvider(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        thinking_config={"reasoning_effort": "low"},
        http_client=http_client,
        sdk_max_retries=0,
        use_environment=False,
    )

    result = asyncio.run(provider.probe_generation_once())

    assert result.text == "OK"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == "main-model"
    assert payload["max_output_tokens"] == 8
    assert payload["reasoning_effort"] == "low"
    assert captured_sdk["max_retries"] == 0
    asyncio.run(provider.aclose())
    asyncio.run(http_client.aclose())


@pytest.mark.parametrize("provider_class", [HProvider, ZProvider])
def test_h_and_z_probes_use_main_model_thinking_and_zero_sdk_retries(
    monkeypatch,
    provider_class,
):
    fake = _FakeOpenAIClient()
    captured: dict = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("ai.openai_provider.openai.AsyncOpenAI", create_client)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200)),
    )
    provider = provider_class(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        thinking_config={"reasoning_effort": "low"},
        http_client=http_client,
        sdk_max_retries=0,
        use_environment=False,
    )

    result = asyncio.run(provider.probe_generation_once())

    assert result.text == "OK"
    assert len(fake.chat.completions.calls) == 1
    call = fake.chat.completions.calls[0]
    assert call["model"] == "main-model"
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] == 8
    assert captured["max_retries"] == 0
    asyncio.run(provider.aclose())
    asyncio.run(http_client.aclose())


@pytest.mark.parametrize(
    ("provider", "provider_type", "expected_class"),
    [
        ("openai", "openai", "OpenAIProvider"),
        ("google", "google", "GoogleProvider"),
        ("h", "openai", "HProvider"),
        ("Z", "openai", "ZProvider"),
        ("custom-anthropic", "anthropic", "AnthropicProvider"),
        ("custom-responses", "openai-response", "OpenAIResponseProvider"),
    ],
)
def test_explicit_factory_preserves_runtime_identity(provider, provider_type, expected_class):
    config = normalize_ai_config(
        provider=provider,
        provider_type=provider_type,
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        enable_thinking=True,
        thinking_config={"reasoning_effort": "low"},
    )
    built = build_provider(config, SINGLE_ATTEMPT)
    inner = built._inner
    try:
        assert type(inner).__name__ == expected_class
        assert inner.model == "main-model"
        assert built._retries == 1
        assert built._timeout == 15.0
    finally:
        asyncio.run(built.aclose())
