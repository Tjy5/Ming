from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import api.ai_settings_service as service_module
from ai.base import GenerationResult
from ai.assessment import VALIDATOR_VERSION
from ai.config import (
    AIConfigurationError,
    EFFECTIVE_PROOF_ENV,
    load_effective_ai_config,
)
from ai.resilient import ResilientProvider
from ai.errors import ProviderFailure
from api.ai_settings_service import AISettingsService, VerificationStore
from api.schemas import AISettingsApplyRequest, AISettingsTestRequest
from fakes import FakeProvider


async def _public_resolver(_host: str, _port: int):
    return ["93.184.216.34"]


class _ProbeProvider(FakeProvider):
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def generate_text_once(self, *args, **kwargs):
        self.calls += 1
        return GenerationResult(text="OK", input_tokens=1, output_tokens=1)

    async def aclose(self):
        self.closed = True


class _Builder:
    def __init__(self):
        self.built = []

    def __call__(self, config, policy, **kwargs):
        inner = _ProbeProvider()
        wrapped = ResilientProvider(inner, timeout=policy.timeout, retries=policy.retries)
        self.built.append((config, policy, wrapped, inner))
        return wrapped


def _draft(**overrides):
    values = {
        "provider": "openai",
        "provider_type": "openai",
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "model": "main-model",
        "simple_model": "small-model",
        "enable_thinking": True,
        "thinking_config": {"reasoning_effort": "low"},
    }
    values.update(overrides)
    return values


def _service(tmp_path: Path, builder: _Builder, environment=None, **kwargs):
    kwargs.setdefault("assessment_loader", lambda _fingerprint: None)
    kwargs.setdefault("assessment_saver", lambda _fingerprint, _report: None)
    return AISettingsService(
        environment={} if environment is None else environment,
        env_path=tmp_path / ".env",
        install_secret_path=tmp_path / ".install-secret",
        resolver=_public_resolver,
        provider_builder=builder,
        **kwargs,
    )


def test_draft_probe_is_isolated_and_exactly_once(tmp_path):
    env = {"AI_PROVIDER": "legacy", "LEGACY_API_KEY": "old"}
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    before = dict(env)

    response = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))

    assert response["ok"] is True
    assert response["verification_token"]
    assert env == before
    assert not (tmp_path / ".env").exists()
    assert len(builder.built) == 1
    assert builder.built[0][3].calls == 1
    assert builder.built[0][3].closed is True


def test_apply_requires_matching_token_and_consumes_it_once(tmp_path):
    env: dict[str, str] = {}
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    old_provider = object()
    slot = {"value": old_provider}

    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    response = asyncio.run(
        service.apply_draft(
            request,
            get_runtime_provider=lambda: slot["value"],
            set_runtime_provider=lambda value: slot.__setitem__("value", value),
        ),
    )

    assert response["effective"] is True
    assert response["status"] == "effective"
    assert slot["value"] is builder.built[1][2]
    assert env["AI_PROVIDER"] == "openai"
    assert env[EFFECTIVE_PROOF_ENV]
    assert load_effective_ai_config(
        env,
        install_secret=service._install_secret(),
    ).model == "main-model"
    assert "sk-test" in (tmp_path / ".env").read_text(encoding="utf-8")

    with pytest.raises(AIConfigurationError) as reused:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: slot["value"],
                set_runtime_provider=lambda value: slot.__setitem__("value", value),
            ),
        )
    assert reused.value.error_code == "ai_test_used"


def test_field_change_invalidates_verification(tmp_path):
    service = _service(tmp_path, _Builder())
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    changed = AISettingsApplyRequest(
        **_draft(model="changed-model"),
        verification_token=tested["verification_token"],
    )
    with pytest.raises(AIConfigurationError) as mismatch:
        asyncio.run(
            service.apply_draft(
                changed,
                get_runtime_provider=lambda: None,
                set_runtime_provider=lambda _value: None,
            ),
        )
    assert mismatch.value.error_code == "ai_test_mismatch"


def test_expired_and_forged_tokens_fail_closed(tmp_path):
    now = [100.0]
    store = VerificationStore(
        process_secret=b"p" * 32,
        ttl_seconds=5,
        clock=lambda: now[0],
        token_factory=lambda: "token-with-enough-entropy",
    )
    service = _service(tmp_path, _Builder(), verification_store=store)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    now[0] = 106.0
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    with pytest.raises(AIConfigurationError) as expired:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: None,
                set_runtime_provider=lambda _value: None,
            ),
        )
    assert expired.value.error_code == "ai_test_expired"

    forged = request.model_copy(update={"verification_token": "forged-token-value"})
    with pytest.raises(AIConfigurationError) as missing:
        asyncio.run(
            service.apply_draft(
                forged,
                get_runtime_provider=lambda: None,
                set_runtime_provider=lambda _value: None,
            ),
        )
    assert missing.value.error_code == "ai_test_required"


def test_swap_failure_rolls_back_file_environment_provider_and_token(tmp_path):
    env = {"EXISTING": "keep"}
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=keep\n", encoding="utf-8")
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    old_provider = object()
    slot = {"value": old_provider}
    fail_once = {"value": True}

    def set_slot(value):
        slot["value"] = value
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("swap failed")

    with pytest.raises(Exception) as failed:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: slot["value"],
                set_runtime_provider=set_slot,
            ),
        )
    assert getattr(failed.value, "error_code", None) == "ai_settings_apply_failed"
    assert slot["value"] is old_provider
    assert env == {"EXISTING": "keep"}
    assert env_path.read_text(encoding="utf-8") == "EXISTING=keep\n"
    assert builder.built[1][3].closed is True

    # A failed transaction releases the reservation, so the same verified
    # draft may be applied again without paying for another probe.
    response = asyncio.run(
        service.apply_draft(
            request,
            get_runtime_provider=lambda: slot["value"],
            set_runtime_provider=lambda value: slot.__setitem__("value", value),
        ),
    )
    assert response["effective"] is True


def test_rollback_setter_failure_does_not_skip_other_recovery_steps(
    tmp_path,
    caplog,
):
    env = {"EXISTING": "keep"}
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=keep\n", encoding="utf-8")
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    old_provider = object()
    slot = {"value": old_provider}
    calls = 0

    def set_slot(value):
        nonlocal calls
        calls += 1
        if calls == 1:
            slot["value"] = value
            raise RuntimeError("primary-secret-canary")
        raise ValueError("rollback-secret-canary")

    with caplog.at_level("ERROR", logger="api.ai_settings_service"):
        with pytest.raises(ProviderFailure) as failed:
            asyncio.run(
                service.apply_draft(
                    request,
                    get_runtime_provider=lambda: slot["value"],
                    set_runtime_provider=set_slot,
                ),
            )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert isinstance(failed.value.__cause__, RuntimeError)
    assert env == {"EXISTING": "keep"}
    assert env_path.read_text(encoding="utf-8") == "EXISTING=keep\n"
    assert builder.built[1][3].closed is True
    assert "runtime_provider" in caplog.text
    assert "primary-secret-canary" not in caplog.text
    assert "rollback-secret-canary" not in caplog.text

    # The reservation is released even when the runtime slot cannot be restored.
    config = service.normalize_draft(_draft())
    reservation = service.verifications.reserve(tested["verification_token"], config)
    service.verifications.release(reservation)


def test_file_restore_failure_still_restores_environment_releases_and_closes(
    tmp_path,
    monkeypatch,
):
    env = {"EXISTING": "keep"}
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=keep\n", encoding="utf-8")
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    fail_once = True

    def set_slot(_value):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("primary failure")

    monkeypatch.setattr(
        service_module,
        "_restore_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("restore failure")),
    )

    with pytest.raises(ProviderFailure) as failed:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: object(),
                set_runtime_provider=set_slot,
            ),
        )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert isinstance(failed.value.__cause__, RuntimeError)
    assert env == {"EXISTING": "keep"}
    assert builder.built[1][3].closed is True
    config = service.normalize_draft(_draft())
    reservation = service.verifications.reserve(tested["verification_token"], config)
    service.verifications.release(reservation)


class _FailingRestoreEnvironment(dict[str, str]):
    fail_restore = False

    def __setitem__(self, key: str, value: str) -> None:
        if self.fail_restore and key == "AI_PROVIDER" and value == "legacy":
            raise RuntimeError("environment restore failure")
        super().__setitem__(key, value)


def test_environment_restore_failure_does_not_skip_token_release_or_close(tmp_path):
    env = _FailingRestoreEnvironment({"AI_PROVIDER": "legacy"})
    env_path = tmp_path / ".env"
    env_path.write_text("AI_PROVIDER=legacy\n", encoding="utf-8")
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    fail_once = True

    def set_slot(_value):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("primary failure")

    env.fail_restore = True
    with pytest.raises(ProviderFailure) as failed:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: object(),
                set_runtime_provider=set_slot,
            ),
        )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert env["AI_PROVIDER"] == "openai"
    assert "OPENAI_API_KEY" not in env
    assert env_path.read_text(encoding="utf-8") == "AI_PROVIDER=legacy\n"
    assert builder.built[1][3].closed is True
    config = service.normalize_draft(_draft())
    reservation = service.verifications.reserve(tested["verification_token"], config)
    service.verifications.release(reservation)


class _ReleaseFailsOnce(VerificationStore):
    fail_release = True

    def release(self, token_hash: str) -> None:
        super().release(token_hash)
        if self.fail_release:
            raise RuntimeError("verification release failure")


def test_verification_release_failure_does_not_skip_candidate_close(tmp_path):
    store = _ReleaseFailsOnce(process_secret=b"p" * 32)
    builder = _Builder()
    service = _service(tmp_path, builder, verification_store=store)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    fail_once = True

    def set_slot(_value):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("primary failure")

    with pytest.raises(ProviderFailure) as failed:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: object(),
                set_runtime_provider=set_slot,
            ),
        )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert builder.built[1][3].closed is True
    store.fail_release = False
    config = service.normalize_draft(_draft())
    reservation = store.reserve(tested["verification_token"], config)
    store.release(reservation)


def test_candidate_close_failure_keeps_primary_cause_and_releases_token(
    tmp_path,
    monkeypatch,
):
    builder = _Builder()
    service = _service(tmp_path, builder)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    request = AISettingsApplyRequest(
        **_draft(),
        verification_token=tested["verification_token"],
    )
    original_close = service_module._close_provider

    async def close_then_fail(provider):
        await original_close(provider)
        raise RuntimeError("candidate close failure")

    monkeypatch.setattr(service_module, "_close_provider", close_then_fail)
    fail_once = True

    def set_slot(_value):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("primary failure")

    with pytest.raises(ProviderFailure) as failed:
        asyncio.run(
            service.apply_draft(
                request,
                get_runtime_provider=lambda: object(),
                set_runtime_provider=set_slot,
            ),
        )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert isinstance(failed.value.__cause__, RuntimeError)
    assert builder.built[1][3].closed is True
    config = service.normalize_draft(_draft())
    reservation = service.verifications.reserve(tested["verification_token"], config)
    service.verifications.release(reservation)


def test_delete_rollback_setter_failure_still_restores_file_and_environment(tmp_path):
    env: dict[str, str] = {}
    builder = _Builder()
    service = _service(tmp_path, builder, env)
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    slot = {"value": None}
    asyncio.run(
        service.apply_draft(
            AISettingsApplyRequest(
                **_draft(),
                verification_token=tested["verification_token"],
            ),
            get_runtime_provider=lambda: slot["value"],
            set_runtime_provider=lambda value: slot.__setitem__("value", value),
        ),
    )
    old_provider = slot["value"]
    env_before = dict(env)
    file_before = (tmp_path / ".env").read_bytes()
    calls = 0

    def set_slot(value):
        nonlocal calls
        calls += 1
        if calls == 1:
            slot["value"] = value
            raise RuntimeError("delete primary failure")
        raise ValueError("delete rollback failure")

    with pytest.raises(ProviderFailure) as failed:
        asyncio.run(
            service.delete_settings(
                "openai",
                get_runtime_provider=lambda: slot["value"],
                set_runtime_provider=set_slot,
            ),
        )

    assert failed.value.error_code == "ai_settings_rollback_failed"
    assert isinstance(failed.value.__cause__, RuntimeError)
    assert env == env_before
    assert (tmp_path / ".env").read_bytes() == file_before
    assert slot["value"] is None
    assert builder.built[1][3].closed is False


@pytest.mark.parametrize("tier", ["excellent", "usable", "high_risk", None])
def test_assessment_tier_never_changes_verified_apply_authorization(tmp_path, tier):
    status = {
        "excellent": "pass",
        "usable": "warn",
        "high_risk": "fail",
    }.get(tier)
    assessment_report = None if tier is None else {
        "tier": tier,
        "results": [
            {
                "scenario": scenario,
                "status": status,
                "explanation": "固定能力评估结果。",
            }
            for scenario in (
                "structured_schema",
                "state_grounding",
                "causal_adjudication",
                "short_memory",
            )
        ],
        "calls_completed": 4,
        "usage": None,
        "assessed_at": "2026-08-10T00:00:00+00:00",
        "validator_version": VALIDATOR_VERSION,
        "stopped_by_transport": False,
        "provider": "openai",
        "provider_type": "openai",
        "model": "main-model",
    }
    builder = _Builder()
    service = _service(
        tmp_path,
        builder,
        assessment_loader=(
            (lambda _fingerprint: None)
            if assessment_report is None
            else (lambda _fingerprint: dict(assessment_report))
        ),
    )
    tested = asyncio.run(service.test_draft(AISettingsTestRequest(**_draft())))
    slot = {"value": None}

    response = asyncio.run(
        service.apply_draft(
            AISettingsApplyRequest(
                **_draft(),
                verification_token=tested["verification_token"],
            ),
            get_runtime_provider=lambda: slot["value"],
            set_runtime_provider=lambda value: slot.__setitem__("value", value),
        ),
    )

    assert response["effective"] is True
    if tier is None:
        assert response["assessment"] is None
    else:
        assert response["assessment"]["tier"] == tier
    assert slot["value"] is builder.built[1][2]
