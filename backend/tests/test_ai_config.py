from __future__ import annotations

import json

import pytest

from ai.config import (
    AIConfigurationError,
    EFFECTIVE_PROOF_ENV,
    EFFECTIVE_PROOF_VERSION,
    EFFECTIVE_PROOF_VERSION_ENV,
    SECRET_MASK,
    assessment_fingerprint,
    config_env_updates,
    config_from_environment,
    effective_config_proof,
    load_effective_ai_config,
    normalize_ai_config,
)


def _config(**overrides):
    values = {
        "provider": "openai",
        "provider_type": "openai",
        "api_key": "sk-secret",
        "base_url": "https://api.example.com/v1/chat/completions",
        "model": "model-main",
        "simple_model": "model-small",
        "enable_thinking": True,
        "enable_thinking_simple": False,
        "thinking_config": {"z": 1, "a": "low"},
        "thinking_config_simple": {"budget": 16},
    }
    values.update(overrides)
    return normalize_ai_config(**values)


def test_normalization_is_stable_and_strips_operation_suffix():
    first = _config(thinking_config={"z": 1, "a": "low"})
    second = _config(thinking_config={"a": "low", "z": 1})

    assert first.base_url == "https://api.example.com/v1"
    assert first.canonical_json() == second.canonical_json()
    assert list(first.thinking_config or {}) == ["a", "z"]


def test_mask_can_only_reuse_secret_for_same_provider():
    config = _config(
        api_key=SECRET_MASK,
        current_provider="openai",
        current_api_key="saved-secret",
    )
    assert config.api_key == "saved-secret"

    with pytest.raises(AIConfigurationError) as exc_info:
        _config(
            provider="vendor-b",
            provider_type="openai",
            api_key=SECRET_MASK,
            current_provider="openai",
            current_api_key="saved-secret",
        )
    assert exc_info.value.error_code == "missing_api_key"


def test_google_never_falls_back_to_openai_environment_values():
    env = {
        "AI_PROVIDER": "google",
        "OPENAI_API_KEY": "must-not-leak",
        "OPENAI_MODEL_NAME": "wrong-model",
        "GOOGLE_MODEL_NAME": "gemini-test",
    }
    with pytest.raises(AIConfigurationError) as exc_info:
        config_from_environment(env)
    assert exc_info.value.error_code == "missing_api_key"


def test_effective_proof_binds_every_runtime_field_and_installation():
    config = _config()
    secret_a = b"a" * 32
    secret_b = b"b" * 32
    proof = effective_config_proof(config, secret_a)

    assert proof != effective_config_proof(_config(model="other"), secret_a)
    assert proof != effective_config_proof(config, secret_b)
    assert assessment_fingerprint(config, secret_a) != proof


def test_assessment_fingerprint_changes_for_every_runtime_field():
    secret = b"f" * 32
    values = {
        "provider": "custom-a",
        "provider_type": "openai",
        "api_key": "sk-secret-a",
        "base_url": "https://api.example.com/v1",
        "model": "model-main",
        "simple_model": "model-small",
        "enable_thinking": True,
        "enable_thinking_simple": False,
        "thinking_config": {"reasoning_effort": "low"},
        "thinking_config_simple": {"budget": 16},
    }
    baseline = normalize_ai_config(**values)
    baseline_fingerprint = assessment_fingerprint(baseline, secret)
    changes = {
        "provider": "custom-b",
        "provider_type": "openai-response",
        "api_key": "sk-secret-b",
        "base_url": "https://other.example.com/v1",
        "model": "model-other",
        "simple_model": "model-other-small",
        "enable_thinking": False,
        "enable_thinking_simple": True,
        "thinking_config": {"reasoning_effort": "high"},
        "thinking_config_simple": {"budget": 32},
    }

    for field, changed_value in changes.items():
        variant = normalize_ai_config(**{**values, field: changed_value})
        assert assessment_fingerprint(variant, secret) != baseline_fingerprint, field


def test_effective_config_requires_matching_saved_proof():
    secret = b"s" * 32
    config = _config()
    env = {key: value for key, value in config_env_updates(config, secret).items() if value is not None}

    loaded = load_effective_ai_config(env, install_secret=secret)
    assert loaded == config

    env["OPENAI_MODEL_NAME"] = "changed-after-save"
    with pytest.raises(AIConfigurationError) as exc_info:
        load_effective_ai_config(env, install_secret=secret)
    assert exc_info.value.error_code == "ai_configuration_invalid"

    env.pop(EFFECTIVE_PROOF_ENV)
    env[EFFECTIVE_PROOF_VERSION_ENV] = EFFECTIVE_PROOF_VERSION
    with pytest.raises(AIConfigurationError) as missing:
        load_effective_ai_config(env, install_secret=secret)
    assert missing.value.error_code == "ai_configuration_required"


def test_canonical_payload_contains_secret_but_public_identity_does_not():
    config = _config()
    assert json.loads(config.canonical_json())["api_key"] == "sk-secret"
    assert "api_key" not in config.public_identity()
