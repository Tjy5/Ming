from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from ai.base import GenerationResult
from ai.provider import ResilientProvider
from api import state as api_state
from api.action_service import ActionAdjudicationError
from db import saves, worlds
from engine.calendar import advance_game_time
from fakes import FakeProvider
from main import app
from models.game import create_initial_state
from engine.settlement import apply_world_deltas
from models.settlement import CompatibilityStatePatchDelta
from models.world import Duration, new_client_action_id, new_delta_id, new_version_id


@pytest.fixture(autouse=True)
def _restore_cache():
    old_state = api_state._state
    old_ref = api_state._get_world_head_ref()
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        api_state._world_head_cache.restore_ref(old_ref)


def _publish_root(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "compatibility.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    snapshot = worlds.load_version(root.version_id)
    api_state._publish_world_head(snapshot.state, snapshot.ref)
    return snapshot


def test_legacy_action_patch_and_time_commit_as_one_version(monkeypatch, tmp_path):
    root = _publish_root(monkeypatch, tmp_path)
    prepared = root.state.model_copy(deep=True)
    prepared.court_prestige += 2

    api_state._provider = ResilientProvider(FakeProvider(), timeout=1, retries=1)
    committed = asyncio.run(
        api_state._set_state(
            prepared,
            action_kind="test_legacy_action",
            raw_text="测试兼容行动",
        ),
    )

    assert committed.court_prestige == root.state.court_prestige + 2
    assert committed.time.clock.absolute_hour == root.state.time.clock.absolute_hour + 1
    settlements = worlds.list_settlements(root.ref.game_id, root.ref.branch_id)
    versions = worlds.list_versions(root.ref.game_id, root.ref.branch_id)
    assert len(settlements) == 1
    assert len(versions) == 2
    assert settlements[0].time_plan.segment.elapsed_hours == 1
    assert settlements[0].duration_reason == "测试 AI 的确定性行动耗时裁决"
    patches = [
        delta
        for delta in settlements[0].deltas
        if isinstance(delta, CompatibilityStatePatchDelta)
    ]
    assert len(patches) == 1
    assert patches[0].before_fields == {"court_prestige": root.state.court_prestige}
    assert patches[0].after_fields == {"court_prestige": committed.court_prestige}


def test_legacy_adapter_rejects_direct_time_writer_without_version(monkeypatch, tmp_path):
    root = _publish_root(monkeypatch, tmp_path)
    prepared = root.state.model_copy(deep=True)
    advance_game_time(prepared.time, Duration(unit="hour", value=1))

    with pytest.raises(ValueError, match="attempted to write time directly"):
        asyncio.run(api_state._set_state(prepared))

    assert worlds.load_branch_head(root.ref.game_id, root.ref.branch_id).ref == root.ref
    assert len(worlds.list_versions(root.ref.game_id, root.ref.branch_id)) == 1


def test_legacy_adapter_uses_ai_duration_instead_of_route_constant(monkeypatch, tmp_path):
    class _TwoDayDurationProvider(FakeProvider):
        async def generate_text_once(self, prompt, **_kwargs):
            assert "ACTION_INTENT=" in prompt
            return GenerationResult(
                text=json.dumps(
                    {
                        "schema_version": 1,
                        "result_tier": "success",
                        "execution_status": "completed",
                        "duration_candidate": {"unit": "day", "value": 2},
                        "duration_reason": "AI 根据当前世界判断需整整两日",
                    },
                    ensure_ascii=False,
                ),
                provider_request_id="dynamic-duration-test",
            )

    root = _publish_root(monkeypatch, tmp_path)
    api_state._provider = ResilientProvider(
        _TwoDayDurationProvider(),
        timeout=1,
        retries=1,
    )
    prepared = root.state.model_copy(deep=True)
    prepared.court_prestige += 1

    committed = asyncio.run(
        api_state._set_state(
            prepared,
            action_kind="minister_dialogue",
            raw_text="与丞相长谈军国大计",
        ),
    )

    settlement = worlds.list_settlements(root.ref.game_id, root.ref.branch_id)[0]
    assert committed.time.clock.absolute_hour == root.state.time.clock.absolute_hour + 48
    assert settlement.time_plan.normalized_duration.duration == Duration(unit="day", value=2)
    assert settlement.duration_reason == "AI 根据当前世界判断需整整两日"


def test_compatibility_patch_compares_set_fields_without_serialization_order():
    state = create_initial_state()
    state.resolved_script_ids = {"birth-1328", "famine-1344", "wandering-1345"}
    changed = apply_world_deltas(
        state,
        [
            CompatibilityStatePatchDelta(
                delta_id=new_delta_id(),
                adapter_name="test_set_order",
                adapter_version="1",
                before_fields={
                    "resolved_script_ids": [
                        "wandering-1345",
                        "birth-1328",
                        "famine-1344",
                    ],
                },
                after_fields={
                    "resolved_script_ids": [
                        "wandering-1345",
                        "birth-1328",
                        "famine-1344",
                        "enlist-1352",
                    ],
                },
            ),
        ],
    )

    assert changed.resolved_script_ids == {
        "birth-1328",
        "famine-1344",
        "wandering-1345",
        "enlist-1352",
    }


def test_advance_month_http_uses_one_replayable_unified_settlement(monkeypatch, tmp_path):
    root = _publish_root(monkeypatch, tmp_path)
    api_state._provider = ResilientProvider(FakeProvider(), timeout=1, retries=1)
    action_id = new_client_action_id()
    body = {
        "client_action_id": str(action_id),
        "expected_parent_version_id": str(root.ref.version_id),
    }
    client = TestClient(app)

    first = client.post("/api/advance-month", json=body)
    replayed = client.post("/api/advance-month", json=body)

    assert first.status_code == 200
    assert replayed.status_code == 200
    first_payload = first.json()
    replayed_payload = replayed.json()
    assert first_payload["result"]["replayed"] is False
    assert replayed_payload["result"]["replayed"] is True
    assert replayed_payload["result"]["version"] == first_payload["result"]["version"]
    assert replayed_payload["state"] == first_payload["state"]
    assert first_payload["result"]["facts"]["time_plan"]["normalized_duration"]["duration"] == {
        "unit": "month",
        "value": 1,
    }
    assert len(worlds.list_settlements(root.ref.game_id, root.ref.branch_id)) == 1
    assert len(worlds.list_versions(root.ref.game_id, root.ref.branch_id)) == 2


def test_advance_month_uses_ai_duration_with_one_month_boundary(monkeypatch, tmp_path):
    class _TwentyNineDayProvider(FakeProvider):
        async def generate_text_once(self, prompt, **_kwargs):
            assert '"action_kind":"wait"' in prompt
            return GenerationResult(
                text=json.dumps(
                    {
                        "schema_version": 1,
                        "result_tier": "success",
                        "execution_status": "completed",
                        "duration_candidate": {"unit": "day", "value": 29},
                        "duration_reason": "AI 依据当前月长度判断等待二十九日",
                    },
                    ensure_ascii=False,
                ),
                provider_request_id="advance-month-dynamic-duration",
            )

    root = _publish_root(monkeypatch, tmp_path)
    api_state._provider = ResilientProvider(
        _TwentyNineDayProvider(),
        timeout=1,
        retries=1,
    )
    response = TestClient(app).post(
        "/api/advance-month",
        json={
            "client_action_id": str(new_client_action_id()),
            "expected_parent_version_id": str(root.ref.version_id),
        },
    )

    assert response.status_code == 200, response.text
    plan = response.json()["result"]["facts"]["time_plan"]
    assert plan["normalized_duration"]["duration"] == {"unit": "day", "value": 29}
    assert plan["segment"]["elapsed_hours"] == 29 * 24
    assert plan["consumer_invocations"][0]["boundary_kind"] == "month"


def test_advance_month_rejects_ai_duration_that_does_not_cross_one_month(
    monkeypatch,
    tmp_path,
):
    class _OneHourProvider(FakeProvider):
        async def generate_text_once(self, _prompt, **_kwargs):
            return GenerationResult(
                text=json.dumps(
                    {
                        "schema_version": 1,
                        "result_tier": "success",
                        "execution_status": "completed",
                        "duration_candidate": {"unit": "hour", "value": 1},
                        "duration_reason": "AI 错误地只裁决一小时",
                    },
                    ensure_ascii=False,
                ),
            )

    root = _publish_root(monkeypatch, tmp_path)
    api_state._provider = ResilientProvider(_OneHourProvider(), timeout=1, retries=1)
    response = TestClient(app).post(
        "/api/advance-month",
        json={
            "client_action_id": str(new_client_action_id()),
            "expected_parent_version_id": str(root.ref.version_id),
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "advance_month_duration_out_of_range"
    assert worlds.load_branch_head(root.ref.game_id, root.ref.branch_id).ref == root.ref
    assert len(worlds.list_versions(root.ref.game_id, root.ref.branch_id)) == 1
    assert len(worlds.list_settlements(root.ref.game_id, root.ref.branch_id)) == 0


def test_first_legacy_ai_failure_does_not_bootstrap_a_world_root(monkeypatch, tmp_path):
    class _FailingStrictProvider(FakeProvider):
        async def generate_text_once(self, _prompt, **_kwargs):
            raise RuntimeError("injected strict duration failure")

    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "first-action-failure.db")
    saves.init_db()
    api_state._state = create_initial_state()
    assert api_state._get_world_head_ref() is None
    api_state._provider = ResilientProvider(
        _FailingStrictProvider(),
        timeout=1,
        retries=1,
    )
    prepared = api_state._state.model_copy(deep=True)
    prepared.court_prestige += 1

    with pytest.raises(ActionAdjudicationError) as exc_info:
        asyncio.run(
            api_state._set_state(
                prepared,
                action_kind="minister_dialogue",
                raw_text="首次行动的 AI 裁决失败",
            ),
        )

    assert exc_info.value.code == "adjudication_provider_error"
    assert api_state._get_world_head_ref() is None
    with worlds._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] == 0


def test_advance_month_http_maps_stale_parent_and_declares_typed_errors(
    monkeypatch,
    tmp_path,
):
    root = _publish_root(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/advance-month",
        json={
            "client_action_id": str(new_client_action_id()),
            "expected_parent_version_id": str(new_version_id()),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "stale_parent_version"
    assert worlds.load_branch_head(root.ref.game_id, root.ref.branch_id).ref == root.ref
    assert len(worlds.list_versions(root.ref.game_id, root.ref.branch_id)) == 1
    responses = app.openapi()["paths"]["/api/advance-month"]["post"]["responses"]
    assert {"200", "404", "409", "422", "500", "503"}.issubset(responses)
