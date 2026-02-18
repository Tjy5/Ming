from ai.provider import MockProvider, ResilientProvider


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
