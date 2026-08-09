from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from ai.assessment import VALIDATOR_VERSION, run_capability_assessment
from ai.base import GenerationResult
from ai.config import (
    EFFECTIVE_PROOF_ENV,
    assessment_fingerprint,
    config_env_updates,
    normalize_ai_config,
)
from api.ai_settings_service import AISettingsService
from api.schemas import AISettingsAssessmentRequest
from db import ai_assessments
from db import saves
from fakes import FakeProvider


PASSING_RESPONSES = [
    {"version": 1, "outcome": "success", "changes": [{"field": "grain", "delta": 2}]},
    {"actors_used": ["林校尉"], "dead_actor_active": False, "changed_fields": ["grain"]},
    {
        "success_degree": "partial",
        "key_factors": ["春汛"],
        "immediate_consequences": ["商路开通"],
        "long_term_risks": ["河道暴露"],
        "new_opportunities": ["新市集"],
    },
    {"remembered_fact": "青瓷印信藏在西库第三格", "default_history_used": False},
]


class _SequenceProvider(FakeProvider):
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    async def generate_text_once(self, *args, **kwargs):
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, BaseException):
            raise value
        return GenerationResult(
            text=json.dumps(value, ensure_ascii=False),
            input_tokens=10,
            output_tokens=5,
        )


async def _public_resolver(_host: str, _port: int):
    return ["93.184.216.34"]


def test_assessment_runs_exactly_four_single_calls_and_scores_locally():
    provider = _SequenceProvider(PASSING_RESPONSES)
    report = asyncio.run(run_capability_assessment(provider))

    assert provider.calls == 4
    assert report["calls_completed"] == 4
    assert report["tier"] == "excellent"
    assert [item["status"] for item in report["results"]] == ["pass"] * 4
    assert report["usage"] == {"input_tokens": 40, "output_tokens": 20}


def test_assessment_score_ignores_historical_route_wording_and_style():
    ornate_nonhistorical_responses = [
        PASSING_RESPONSES[0],
        PASSING_RESPONSES[1],
        {
            "success_degree": "partial",
            "key_factors": ["玩家另辟路线，辞采不作为评分条件"],
            "immediate_consequences": ["结果刻意不模仿任何正史答案"],
            "long_term_risks": ["措辞华丽，但仍只按结构合同评分"],
            "new_opportunities": ["完全不同的具体路线仍可通过"],
        },
        PASSING_RESPONSES[3],
    ]

    baseline = asyncio.run(run_capability_assessment(_SequenceProvider(PASSING_RESPONSES)))
    variant = asyncio.run(
        run_capability_assessment(_SequenceProvider(ornate_nonhistorical_responses)),
    )

    assert variant["tier"] == baseline["tier"] == "excellent"
    assert [item["status"] for item in variant["results"]] == [
        item["status"] for item in baseline["results"]
    ]


def test_assessment_response_log_and_database_never_echo_secrets_or_model_output(
    tmp_path,
    monkeypatch,
    caplog,
):
    canaries = {
        "api_key": "sk-assessment-api-key-canary",
        "raw_response": "assessment-raw-response-canary",
        "chain_of_thought": "assessment-chain-of-thought-canary",
        "player_save": "assessment-player-save-canary",
    }
    responses = [
        PASSING_RESPONSES[0],
        PASSING_RESPONSES[1],
        {
            "success_degree": "partial",
            "key_factors": [canaries["raw_response"]],
            "immediate_consequences": [canaries["chain_of_thought"]],
            "long_term_risks": [canaries["player_save"]],
            "new_opportunities": ["safe structured value"],
        },
        PASSING_RESPONSES[3],
    ]
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assessments.db")
    saves.init_db()
    provider = _SequenceProvider(responses)
    service = AISettingsService(
        environment={},
        env_path=tmp_path / ".env",
        install_secret_path=tmp_path / ".install-secret",
        resolver=_public_resolver,
        provider_builder=lambda _config, _policy, **_kwargs: provider,
    )

    response = asyncio.run(
        service.assess_draft(
            AISettingsAssessmentRequest(
                provider="openai",
                provider_type="openai",
                api_key=canaries["api_key"],
                base_url="https://api.example.com/v1",
                model="main-model",
            ),
        ),
    )

    public_payload = json.dumps(response, ensure_ascii=False)
    database_bytes = (tmp_path / "assessments.db").read_bytes()
    for canary in canaries.values():
        assert canary not in public_payload
        assert canary.encode() not in database_bytes
        assert canary not in caplog.text


def test_transport_failure_stops_remaining_scenarios_without_retry():
    provider = _SequenceProvider([PASSING_RESPONSES[0], RuntimeError("secret upstream body")])
    report = asyncio.run(run_capability_assessment(provider))

    assert provider.calls == 2
    assert report["calls_completed"] == 2
    assert report["stopped_by_transport"] is True
    assert len(report["results"]) == 4
    assert "secret upstream body" not in json.dumps(report, ensure_ascii=False)


def test_content_validation_failure_continues_all_remaining_scenarios():
    provider = _SequenceProvider(
        [
            {"version": 99, "outcome": "unknown", "changes": []},
            *PASSING_RESPONSES[1:],
        ],
    )

    report = asyncio.run(run_capability_assessment(provider))

    assert provider.calls == 4
    assert report["calls_completed"] == 4
    assert report["stopped_by_transport"] is False
    assert report["tier"] == "high_risk"
    assert [item["status"] for item in report["results"]] == [
        "fail",
        "pass",
        "pass",
        "pass",
    ]


def test_cancel_propagates_and_does_not_start_later_scenarios():
    provider = _SequenceProvider([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_capability_assessment(provider))
    assert provider.calls == 1


def test_assessment_store_round_trip_and_corruption_degrades_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assessments.db")
    saves.init_db()
    report = asyncio.run(
        run_capability_assessment(_SequenceProvider(PASSING_RESPONSES)),
    )
    report.update(
        {
            "provider": "openai",
            "provider_type": "openai",
            "model": "main-model",
        },
    )
    ai_assessments.save_assessment("private-fingerprint", report)
    assert ai_assessments.load_assessment("private-fingerprint") == report

    with sqlite3.connect(tmp_path / "assessments.db") as conn:
        conn.execute(
            "UPDATE ai_assessments SET report_json = ? WHERE fingerprint = ?",
            ("not-json", "private-fingerprint"),
        )
    assert ai_assessments.load_assessment("private-fingerprint") is None

    ai_assessments.save_assessment("private-fingerprint", report)
    with sqlite3.connect(tmp_path / "assessments.db") as conn:
        conn.execute(
            "UPDATE ai_assessments SET report_json = ? WHERE fingerprint = ?",
            (json.dumps({"tier": "excellent"}), "private-fingerprint"),
        )
    assert ai_assessments.load_assessment("private-fingerprint") is None


def test_assessment_store_rejects_unknown_secret_bearing_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assessments.db")
    saves.init_db()
    report = asyncio.run(
        run_capability_assessment(_SequenceProvider(PASSING_RESPONSES)),
    )
    report.update(
        {
            "provider": "openai",
            "provider_type": "openai",
            "model": "main-model",
            "api_key": "sk-persistence-secret-canary",
        },
    )

    with pytest.raises(ValueError, match="invalid AI assessment report"):
        ai_assessments.save_assessment("private-fingerprint", report)

    assert "sk-persistence-secret-canary" not in (
        tmp_path / "assessments.db"
    ).read_bytes().decode("utf-8", errors="ignore")


def test_matching_assessment_survives_service_restart_and_old_validator_is_hidden(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "assessments.db")
    saves.init_db()
    environment: dict[str, str] = {}
    secret_path = tmp_path / ".install-secret"
    first_service = AISettingsService(
        environment=environment,
        env_path=tmp_path / ".env",
        install_secret_path=secret_path,
    )
    config = normalize_ai_config(
        provider="openai",
        provider_type="openai",
        api_key="sk-restart-secret-canary",
        base_url="https://api.example.com/v1",
        model="main-model",
        simple_model="small-model",
        enable_thinking=True,
        thinking_config={"reasoning_effort": "low"},
    )
    install_secret = first_service._install_secret()
    environment.update(
        {
            key: value
            for key, value in config_env_updates(config, install_secret).items()
            if value is not None
        },
    )
    report = asyncio.run(
        run_capability_assessment(_SequenceProvider(PASSING_RESPONSES)),
    )
    report.update(
        {
            "provider": config.provider,
            "provider_type": config.provider_type,
            "model": config.model,
        },
    )
    fingerprint = assessment_fingerprint(config, install_secret)
    ai_assessments.save_assessment(fingerprint, report)

    restarted_service = AISettingsService(
        environment=environment,
        env_path=tmp_path / ".env",
        install_secret_path=secret_path,
    )
    restored = restarted_service.current_settings("openai")
    assert restored["assessment"]["tier"] == "excellent"
    assert restored["assessment"]["config_matches"] is True
    assert "sk-restart-secret-canary" not in json.dumps(restored, ensure_ascii=False)

    stale = dict(report, validator_version="obsolete-validator")
    ai_assessments.save_assessment(fingerprint, stale)
    assert restarted_service.current_settings("openai")["assessment"] is None

    ai_assessments.save_assessment(fingerprint, report)
    environment.pop(EFFECTIVE_PROOF_ENV)
    unproved = restarted_service.current_settings("openai")
    assert unproved["effective"] is False
    assert unproved["assessment"] is None
