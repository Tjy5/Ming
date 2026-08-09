from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai.base import GenerationResult
from ai.config import AIConfigurationError
from ai.resilient import ResilientProvider
from api import settings_routes
from api import state as api_state
from api.ai_settings_service import (
    AISettingsService,
    set_ai_settings_service_for_testing,
)
from api.schemas import (
    AISettingsApplyRequest,
    AISettingsAssessmentRequest,
    AISettingsTestRequest,
)
from fakes import FakeProvider
from main import app


async def _resolver(_host: str, _port: int):
    return ["93.184.216.34"]


class _SmartProvider(FakeProvider):
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def generate_text_once(self, prompt: str, **kwargs):
        self.calls += 1
        if "version 必须为 1" in prompt:
            payload = {"version": 1, "outcome": "success", "changes": [{"field": "grain", "delta": 2}]}
        elif "周参军已死亡" in prompt:
            payload = {"actors_used": ["林校尉"], "dead_actor_active": False, "changed_fields": ["grain"]}
        elif "借春汛" in prompt:
            payload = {
                "success_degree": "partial",
                "key_factors": ["水势"],
                "immediate_consequences": ["开路"],
                "long_term_risks": ["暴露"],
                "new_opportunities": ["贸易"],
            }
        elif "青瓷印信" in prompt:
            payload = {"remembered_fact": "青瓷印信藏在西库第三格", "default_history_used": False}
        else:
            return GenerationResult(text="OK")
        return GenerationResult(text=json.dumps(payload, ensure_ascii=False))

    async def aclose(self):
        self.closed = True


class _Builder:
    def __init__(self):
        self.items = []

    def __call__(self, config, policy, **kwargs):
        inner = _SmartProvider()
        wrapped = ResilientProvider(inner, timeout=policy.timeout, retries=policy.retries)
        self.items.append((config, policy, wrapped, inner))
        return wrapped


def _draft():
    return {
        "provider": "openai",
        "provider_type": "openai",
        "api_key": "sk-route-test",
        "base_url": "https://api.example.com/v1",
        "model": "route-model",
        "enable_thinking": True,
        "thinking_config": {"reasoning_effort": "low"},
    }


@pytest.fixture
def route_service(tmp_path):
    builder = _Builder()
    reports = {}
    service = AISettingsService(
        environment={},
        env_path=tmp_path / ".env",
        install_secret_path=tmp_path / ".install-secret",
        resolver=_resolver,
        provider_builder=builder,
        assessment_loader=lambda fingerprint: reports.get(fingerprint),
        assessment_saver=lambda fingerprint, report: reports.__setitem__(fingerprint, report),
    )
    set_ai_settings_service_for_testing(service)
    previous = api_state._provider
    api_state._provider = None
    yield service, builder, reports
    api_state._provider = previous
    set_ai_settings_service_for_testing(None)


def test_route_test_assess_apply_share_config_and_assessment_does_not_consume_token(route_service):
    service, builder, reports = route_service
    tested = asyncio.run(
        settings_routes.test_ai_connection(AISettingsTestRequest(**_draft())),
    )
    assessed = asyncio.run(
        settings_routes.assess_ai_capability(AISettingsAssessmentRequest(**_draft())),
    )
    applied = asyncio.run(
        settings_routes.update_ai_settings(
            AISettingsApplyRequest(
                **_draft(),
                verification_token=tested["verification_token"],
            ),
        ),
    )

    assert assessed["tier"] == "excellent"
    assert assessed["calls_completed"] == 4
    assert reports
    assert applied["effective"] is True
    assert api_state._provider is builder.items[2][2]
    identities = [item[0].public_identity() for item in builder.items]
    assert identities[0] == identities[1] == identities[2]
    assert builder.items[0][3].calls == 1
    assert builder.items[1][3].calls == 4

    runtime_result = asyncio.run(
        api_state._get_provider().generate_text_once("first gameplay AI request"),
    )
    assert runtime_result.text == "OK"
    assert builder.items[2][3].calls == 1


def test_route_rejects_missing_key_with_safe_diagnostic(route_service):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            settings_routes.test_ai_connection(
                AISettingsTestRequest(**{**_draft(), "api_key": ""}),
            ),
        )
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["error_code"] == "missing_api_key"
    assert detail["fix_hint"]
    assert detail["request_id"].startswith("ai_")
    assert "sk-route-test" not in json.dumps(detail, ensure_ascii=False)


def test_openapi_contains_typed_test_assess_and_apply_contracts():
    schema = app.openapi()
    assert "/api/settings/ai/test" in schema["paths"]
    assert "/api/settings/ai/assess" in schema["paths"]
    components = schema["components"]["schemas"]
    for name in (
        "AISettingsTestRequest",
        "AISettingsTestResponse",
        "AISettingsAssessmentRequest",
        "AISettingsAssessmentResponse",
        "AISettingsApplyRequest",
        "AISettingsErrorEnvelope",
        "AISettingsResponse",
        "ErrorResponse",
    ):
        assert name in components
    error_properties = components["ErrorResponse"]["properties"]
    for field in ("fix_hint", "request_id", "provider_summary", "retryable"):
        assert field in error_properties


def test_request_validation_never_exposes_or_logs_secret_input(caplog):
    canary = "sk-validation-secret-canary Authorization: Bearer validation-leak"
    client = TestClient(app)

    try:
        with caplog.at_level(logging.WARNING, logger="main"):
            response = client.post(
                "/api/settings/ai/test",
                json={
                    **_draft(),
                    # A wrong-typed secret is included in Pydantic's raw validation
                    # details; the public handler must project only the field name.
                    "api_key": {"secret": canary},
                },
            )
    finally:
        client.close()

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "invalid_ai_settings"
    assert detail["fix_hint"]
    assert detail["request_id"].startswith("ai_")
    assert detail["details"] == {"fields": ["api_key"]}
    assert canary not in response.text
    assert "validation-leak" not in response.text
    assert canary not in caplog.text
    assert "validation-leak" not in caplog.text


def test_runtime_rejects_environment_config_without_effective_proof(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "deployment-key-must-not-be-runtime")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "deployment-model")
    monkeypatch.delenv("AI_EFFECTIVE_CONFIG_PROOF", raising=False)
    monkeypatch.delenv("AI_EFFECTIVE_CONFIG_VERSION", raising=False)
    api_state._provider = None

    with pytest.raises(HTTPException) as exc_info:
        api_state._get_provider()
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "ai_configuration_required"
