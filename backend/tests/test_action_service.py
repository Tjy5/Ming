from __future__ import annotations

import json
import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ai.base import GenerationResult
from api.action_routes import set_action_service_for_testing
from api.action_service import (
    AIActionAdjudicator,
    ActionAdjudicationError,
    ActionService,
)
from db import saves, worlds
from engine.settlement import (
    SettlementValidationError,
    apply_world_deltas,
    validate_adjudication_proposal,
    validate_final_state,
)
from main import app
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    EntityWorldDelta,
    FieldChange,
    MetricWorldDelta,
    PlayerWorldDelta,
)
from models.world import (
    Duration,
    EntitySource,
    PersonEntity,
    new_client_action_id,
    new_delta_id,
    new_entity_id,
)


def _store(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "action-service.db")
    saves.init_db()
    initial = create_initial_state()
    root = worlds.create_game_with_root(initial)
    return worlds.load_version(root.version_id).state, root


def _intent(root, *, action_id=None, text="按兵不动") -> ActionIntent:
    return ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=action_id or new_client_action_id(),
        raw_text=text,
        action_kind="wait",
        mode="governance",
    )


def _proposal(before: int, *, value: int = 1) -> AdjudicationProposal:
    return AdjudicationProposal(
        result_tier="success",
        key_factors=["等待让局势继续演化"],
        immediate_changes=["连续等待次数增加"],
        execution_status="completed",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="等待一小时观察局势",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="consecutive_waits",
                operation="increment",
                before_value=before,
                value=value,
            ),
        ],
    )


def _death_proposal(
    intent: ActionIntent,
    *,
    direct_cause: str = "亲临前线时遭敌军伏击重创",
    key_factors: list[str] | None = None,
) -> AdjudicationProposal:
    factors = list(key_factors or ["主角亲自进入高危战场", "护卫已被敌军切断"])
    return AdjudicationProposal(
        result_tier="failure",
        key_factors=factors,
        immediate_changes=["主角死亡，当前世界线终止"],
        execution_status="failed",
        duration_candidate=Duration(unit="hour", value=3),
        duration_reason="伏击与突围持续三小时",
        deltas=[
            PlayerWorldDelta(
                delta_id=new_delta_id(),
                operation="death",
                before_value="alive",
                value="dead",
                trigger_action=intent.client_action_id,
                direct_cause=direct_cause,
                key_factors=factors,
                causal_summary=f"本次行动直接导致：{direct_cause}",
            ),
        ],
    )


class _StaticAdjudicator:
    def __init__(self, proposal: AdjudicationProposal):
        self.proposal = proposal
        self.calls = 0

    async def adjudicate(self, intent, state):
        self.calls += 1
        return self.proposal


def test_proposal_validator_rejects_duplicate_ids_conflicts_and_unknown_references():
    state = create_initial_state()
    # The validator does not consult storage; UUID identities only need to be
    # internally consistent for this pure contract test.
    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    intent = _intent(root_like)
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(
            intent,
            state,
            AdjudicationProposal(result_tier="success"),
        )
    assert exc_info.value.code == "duration_required"

    repeated_id = new_delta_id()
    duplicate = AdjudicationProposal(
        result_tier="success",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="测试重复 delta 校验",
        deltas=[
            MetricWorldDelta(
                delta_id=repeated_id,
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=state.civil_morale,
                value=1,
            ),
            MetricWorldDelta(
                delta_id=repeated_id,
                target_scope="world",
                field="military_morale",
                operation="increment",
                before_value=state.military_morale,
                value=1,
            ),
        ],
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(intent, state, duplicate)
    assert exc_info.value.code == "duplicate_delta_id"

    conflict = AdjudicationProposal(
        result_tier="success",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="测试冲突 delta 校验",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="increment",
                before_value=state.civil_morale,
                value=1,
            ),
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="civil_morale",
                operation="set",
                before_value=state.civil_morale,
                value=50,
            ),
        ],
    )
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(intent, state, conflict)
    assert exc_info.value.code == "delta_conflict"


def test_entity_end_cannot_restore_status_and_create_rejects_dangling_references():
    state = create_initial_state()
    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    intent = _intent(root_like)
    existing_id = new_entity_id()
    state.entity_registry[existing_id] = PersonEntity(
        entity_id=existing_id,
        display_name="现有主体",
        source=EntitySource(kind="system"),
    )
    invalid_end = AdjudicationProposal(
        result_tier="success",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="测试结束主体校验",
        deltas=[
            EntityWorldDelta(
                delta_id=new_delta_id(),
                operation="end",
                target_entity_id=existing_id,
                before_status="active",
                changes=[FieldChange(field="available", before_value=True, value=True)],
            ),
        ],
    )
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(intent, state, invalid_end)
    assert exc_info.value.code == "invalid_entity_end"

    created_id = new_entity_id()
    dangling_id = new_entity_id()
    dangling_create = AdjudicationProposal(
        result_tier="success",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="测试悬空引用校验",
        deltas=[
            EntityWorldDelta(
                delta_id=new_delta_id(),
                operation="create",
                target_entity_id=created_id,
                entity=PersonEntity(
                    entity_id=created_id,
                    display_name="悬空主体",
                    source=EntitySource(kind="adjudication"),
                    faction_ids=[dangling_id],
                ),
            ),
        ],
    )
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_adjudication_proposal(intent, state, dangling_create)
    assert exc_info.value.code == "unknown_entity_reference"


def test_apply_world_deltas_is_pure_and_checks_before_value():
    state = create_initial_state()
    proposal = _proposal(state.consecutive_waits, value=2)

    changed = apply_world_deltas(state, proposal.deltas)

    assert state.consecutive_waits == 0
    assert changed.consecutive_waits == 2
    assert changed is not state

    stale = _proposal(99)
    with pytest.raises(SettlementValidationError) as exc_info:
        apply_world_deltas(state, stale.deltas)
    assert exc_info.value.code == "delta_precondition_failed"


def test_final_state_validation_rejects_registry_and_player_identity_regressions():
    state = create_initial_state()
    player_id = new_entity_id()
    state.entity_registry[player_id] = PersonEntity(
        entity_id=player_id,
        display_name="稳定主角",
        source=EntitySource(kind="system"),
        roles=["player_character"],
    )
    state.player_world_status = state.player_world_status.model_copy(
        update={"player_character_id": player_id},
    )

    missing_entity = state.model_copy(deep=True)
    missing_entity.entity_registry.clear()
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_final_state(state, missing_entity)
    assert exc_info.value.code == "entity_registry_regression"

    missing_player = state.model_copy(deep=True)
    missing_player.player_world_status = missing_player.player_world_status.model_copy(
        update={"player_character_id": None},
    )
    with pytest.raises(SettlementValidationError) as exc_info:
        validate_final_state(state, missing_player)
    assert exc_info.value.code == "player_identity_regression"


def test_action_service_commits_once_and_replay_skips_ai(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root)
    adjudicator = _StaticAdjudicator(_proposal(initial.consecutive_waits))
    service = ActionService(adjudicator=adjudicator)

    first = service.execute_sync(intent)
    replay = service.execute_sync(intent)

    assert first.result.replayed is False
    assert replay.result.replayed is True
    assert adjudicator.calls == 1
    assert first.state.consecutive_waits == 1
    assert replay.state == first.state
    assert worlds.load_branch_head(root.game_id, root.branch_id).state == first.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_time_only_action_commits_one_version_and_replay_preserves_time_facts(
    monkeypatch,
    tmp_path,
):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, text="静候一日一时")
    proposal = AdjudicationProposal(
        result_tier="success",
        execution_status="completed",
        duration_candidate=Duration(unit="hour", value=25),
        duration_reason="等待局势自然演化",
    )
    adjudicator = _StaticAdjudicator(proposal)
    service = ActionService(adjudicator=adjudicator)

    first = service.execute_sync(intent)
    replay = service.execute_sync(intent)

    assert first.state.time.clock is not None
    assert initial.time.clock is not None
    assert first.state.time.clock.absolute_hour == initial.time.clock.absolute_hour + 25
    assert first.result.facts.time_plan is not None
    assert first.result.facts.time_plan.normalized_duration.elapsed_hours == 25
    assert first.result.facts.duration_reason == "等待局势自然演化"
    assert replay.result.replayed is True
    assert replay.result.facts.time_plan == first.result.facts.time_plan
    assert replay.state == first.state
    assert adjudicator.calls == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2
    assert worlds.list_settlements(root.game_id, root.branch_id)[0].time_plan == (
        first.result.facts.time_plan
    )
    assert (
        worlds.list_settlements(root.game_id, root.branch_id)[0].duration_reason
        == "等待局势自然演化"
    )


def test_duration_and_world_delta_commit_atomically(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    proposal = _proposal(initial.consecutive_waits)
    proposal.duration_candidate = Duration(unit="month", value=1)
    proposal.duration_reason = "等待一个历法月后再观察结果"

    execution = ActionService(
        adjudicator=_StaticAdjudicator(proposal),
    ).execute_sync(_intent(root, text="等待一月并记录局势"))

    assert execution.state.consecutive_waits == 1
    assert execution.state.time.calendar is not None
    assert execution.state.time.calendar.month == 11
    assert execution.result.facts.time_plan is not None
    assert execution.result.facts.deltas[: len(proposal.deltas)] == proposal.deltas
    assert execution.result.facts.deltas[-1].delta_type == "elapsed_state_patch"


def test_ordinary_validation_and_application_cannot_bypass_terminal_contract():
    state = create_initial_state()
    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    intent = _intent(root_like, text="孤身冲入敌阵")
    proposal = _death_proposal(intent)

    with pytest.raises(SettlementValidationError) as validation_error:
        validate_adjudication_proposal(intent, state, proposal)
    assert validation_error.value.code == "terminal_contract_unavailable"

    with pytest.raises(SettlementValidationError) as application_error:
        apply_world_deltas(state, proposal.deltas)
    assert application_error.value.code == "terminal_contract_unavailable"


@pytest.mark.parametrize(
    ("action_text", "direct_cause", "factors"),
    [
        (
            "亲率轻骑冲击敌军中军",
            "突击敌军中军时被乱箭贯穿胸腹",
            ["主角亲自进入箭阵", "护卫阵形已经溃散"],
        ),
        (
            "被俘后拒绝交出城防密令",
            "被俘后因拒绝投降而遭敌军处决",
            ["主角已被敌军拘押", "交涉彻底破裂"],
        ),
        (
            "染疫仍连续巡视隔离营",
            "重疫恶化并在缺医少药的隔离营中死亡",
            ["主角持续暴露于疫区", "当前药材储备不足"],
        ),
    ],
)
def test_terminal_action_commits_death_record_and_replays_once(
    monkeypatch,
    tmp_path,
    action_text,
    direct_cause,
    factors,
):
    _initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, text=action_text)
    adjudicator = _StaticAdjudicator(
        _death_proposal(intent, direct_cause=direct_cause, key_factors=factors),
    )
    service = ActionService(adjudicator=adjudicator)

    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)

    status = committed.state.player_world_status
    assert status.life_status == "dead"
    assert status.terminal_settlement_id == committed.result.facts.settlement_id
    assert status.terminal_version_id == committed.result.version.version_id
    terminal = worlds.get_terminal_record(committed.result.facts.settlement_id)
    assert terminal.trigger_action == intent.client_action_id
    assert terminal.direct_cause == direct_cause
    assert terminal.key_factors == factors
    assert terminal.version_id == committed.result.version.version_id
    assert replayed.result.replayed is True
    assert replayed.state == committed.state
    assert adjudicator.calls == 1
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2

    next_intent = _intent(
        committed.result.version,
        action_id=new_client_action_id(),
        text="死亡后继续下一回合",
    )
    with pytest.raises(worlds.WorldTerminalStateError):
        service.execute_sync(next_intent)
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1

    # A terminal snapshot is not a playable fork root; only the protected
    # pre-death version may be used to create an alternate world line.
    with pytest.raises(worlds.WorldTerminalStateError):
        worlds.create_branch_from_version(committed.result.version.version_id)
    fork = worlds.create_branch_from_version(root.version_id)
    assert fork.parent_version_id == root.version_id
    assert worlds.load_version(fork.version_id).state.player_world_status.life_status == "alive"


def test_terminal_record_insert_failure_rolls_back_all_rows_and_allows_retry(
    monkeypatch,
    tmp_path,
):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, text="孤身断后")
    service = ActionService(adjudicator=_StaticAdjudicator(_death_proposal(intent)))

    def _fail_terminal_insert(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected terminal insert failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(worlds, "_insert_terminal_record", _fail_terminal_insert)
        with pytest.raises(worlds.WorldStorageError):
            service.execute_sync(intent)

    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.load_branch_head(root.game_id, root.branch_id).state == initial
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 1
    assert worlds.get_action_request(
        root.game_id,
        root.branch_id,
        intent.client_action_id,
    ) is None
    with saves._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM terminal_records").fetchone()[0] == 0

    retried = service.execute_sync(intent)
    assert retried.state.player_world_status.life_status == "dead"
    with saves._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM terminal_records").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("proposal", "expected_code"),
    [
        (
            AdjudicationProposal(
                result_tier="success",
                duration_candidate=Duration(unit="year", value=2),
                duration_reason="超长行动必须切分 checkpoint",
            ),
            "activity_contract_required",
        ),
    ],
)
def test_oversized_short_time_contract_has_zero_durable_effect(
    monkeypatch,
    tmp_path,
    proposal,
    expected_code,
):
    initial, root = _store(monkeypatch, tmp_path)
    service = ActionService(adjudicator=_StaticAdjudicator(proposal))

    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(_intent(root, text="尝试尚不可用的长行动"))

    assert exc_info.value.code == expected_code
    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.load_branch_head(root.game_id, root.branch_id).state == initial
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 1


def test_concurrent_service_double_click_calls_ai_once(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root)

    class _YieldingAdjudicator(_StaticAdjudicator):
        async def adjudicate(self, intent, state):
            self.calls += 1
            await asyncio.sleep(0.02)
            return self.proposal

    adjudicator = _YieldingAdjudicator(_proposal(initial.consecutive_waits))
    service = ActionService(adjudicator=adjudicator)

    async def _run_both():
        return await asyncio.gather(service.execute(intent), service.execute(intent))

    results = asyncio.run(_run_both())

    assert sorted(item.result.replayed for item in results) == [False, True]
    assert adjudicator.calls == 1
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_action_service_rechecks_head_after_ai(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, text="等待中的旧请求")

    class _RacingAdjudicator:
        async def adjudicate(self, _intent, _state):
            competing_intent = _intent.model_copy(
                update={
                    "client_action_id": new_client_action_id(),
                    "raw_text": "先完成的请求",
                },
            )
            competing_state = initial.model_copy(deep=True)
            competing_state.consecutive_waits += 1
            worlds.commit_settlement(
                competing_intent,
                competing_state,
                _proposal(initial.consecutive_waits),
            )
            return _proposal(initial.consecutive_waits)

    service = ActionService(adjudicator=_RacingAdjudicator())

    with pytest.raises(worlds.StaleParentVersionError):
        service.execute_sync(intent)
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_public_action_http_path_runs_ai_db_reload_and_replay(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root)
    adjudicator = _StaticAdjudicator(_proposal(initial.consecutive_waits))
    service = ActionService(adjudicator=adjudicator)
    set_action_service_for_testing(service)
    try:
        with TestClient(app) as client:
            first = client.post("/api/actions", json=intent.model_dump(mode="json"))
            replay = client.post("/api/actions", json=intent.model_dump(mode="json"))
            conflict = client.post(
                "/api/actions",
                json=intent.model_copy(update={"raw_text": "改写后的动作"}).model_dump(mode="json"),
            )
    finally:
        set_action_service_for_testing(None)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert conflict.status_code == 409, conflict.text
    first_payload = first.json()
    replay_payload = replay.json()
    assert first_payload["result"]["replayed"] is False
    assert replay_payload["result"]["replayed"] is True
    assert first_payload["state"]["consecutive_waits"] == 1
    assert first_payload["narrative"]["path_id"] == "unified_action"
    assert first_payload["narrative"]["context_version_id"] == first_payload["result"]["version"]["version_id"]
    assert first_payload["narrative"]["request_id"]
    assert first_payload["narrative"]["progress_stages"][0] == "context_ready"
    assert first_payload["narrative"]["progress_stages"][-1] == "validated"
    assert adjudicator.calls == 1
    assert conflict.json()["detail"]["error_code"] == "idempotency_conflict"
    reloaded = worlds.load_branch_head(root.game_id, root.branch_id)
    assert str(reloaded.ref.version_id) == first_payload["result"]["version"]["version_id"]
    assert reloaded.state.consecutive_waits == 1


def test_public_terminal_action_returns_committed_cause_and_blocks_next_action(
    monkeypatch,
    tmp_path,
):
    _initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root, text="孤军突围并亲自断后")
    cause = "断后时被追兵长矛刺中要害"
    service = ActionService(
        adjudicator=_StaticAdjudicator(
            _death_proposal(
                intent,
                direct_cause=cause,
                key_factors=["主角独自留在狭窄谷口", "援军尚未抵达"],
            ),
        ),
    )
    set_action_service_for_testing(service)
    try:
        with TestClient(app) as client:
            terminal = client.post(
                "/api/actions",
                json=intent.model_dump(mode="json"),
            )
            assert terminal.status_code == 200, terminal.text
            terminal_payload = terminal.json()
            next_intent = _intent(
                SimpleNamespace(
                    game_id=root.game_id,
                    branch_id=root.branch_id,
                    version_id=terminal_payload["result"]["version"]["version_id"],
                ),
                text="死亡后继续行动",
            )
            blocked = client.post(
                "/api/actions",
                json=next_intent.model_dump(mode="json"),
            )
    finally:
        set_action_service_for_testing(None)

    assert terminal_payload["state"]["player_world_status"]["life_status"] == "dead"
    assert cause in terminal_payload["narrative"]["text"]
    assert "继承" not in terminal_payload["narrative"]["text"]
    assert "换视角" not in terminal_payload["narrative"]["text"]
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error_code"] == "world_terminal"
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_public_action_failure_is_typed_and_has_zero_durable_effect(monkeypatch, tmp_path):
    _, root = _store(monkeypatch, tmp_path)
    intent = _intent(root)

    class _FailingAdjudicator:
        async def adjudicate(self, _intent, _state):
            raise ActionAdjudicationError(
                "adjudication_provider_error",
                "AI 裁决调用失败，世界状态未提交",
            )

    set_action_service_for_testing(ActionService(adjudicator=_FailingAdjudicator()))
    try:
        with TestClient(app) as client:
            response = client.post("/api/actions", json=intent.model_dump(mode="json"))
    finally:
        set_action_service_for_testing(None)

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "adjudication_provider_error"
    assert worlds.get_branch_head(root.game_id, root.branch_id) == root
    assert worlds.list_settlements(root.game_id, root.branch_id) == []
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 1


def test_public_action_recovers_cache_after_committed_publish_failure(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    intent = _intent(root)
    adjudicator = _StaticAdjudicator(_proposal(initial.consecutive_waits))
    set_action_service_for_testing(ActionService(adjudicator=adjudicator))

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("injected cache publish failure")

    monkeypatch.setattr("api.action_routes._publish_world_head", fail_publish)
    try:
        with TestClient(app) as client:
            response = client.post("/api/actions", json=intent.model_dump(mode="json"))
    finally:
        set_action_service_for_testing(None)

    assert response.status_code == 200, response.text
    assert response.json()["state"]["consecutive_waits"] == 1
    assert response.json()["result"]["replayed"] is False
    assert worlds.load_branch_head(root.game_id, root.branch_id).state.consecutive_waits == 1
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_openapi_declares_typed_action_contract():
    schema = app.openapi()
    operation = schema["paths"]["/api/actions"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ActionIntent",
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ActionExecutionResponse",
    )
    assert operation["responses"]["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ActionErrorEnvelope",
    )


def test_invalid_public_action_request_uses_typed_safe_error():
    with TestClient(app) as client:
        response = client.post("/api/actions", json={"raw_text": ""})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error_code": "invalid_action_request",
        "message": "行动请求字段校验失败",
        "details": {
            "fields": [
                "branch_id",
                "client_action_id",
                "expected_parent_version_id",
                "game_id",
                "raw_text",
            ],
        },
    }


def test_ai_adjudicator_uses_one_json_call_and_has_no_hidden_fallback():
    class _Provider:
        def __init__(self, text: str):
            self.text = text
            self.calls = 0
            self.prompts = []

        async def generate_text_once(self, *args, **kwargs):
            self.calls += 1
            self.prompts.append(args[0])
            return GenerationResult(text=self.text, provider_request_id="provider-request")

    valid_provider = _Provider(json.dumps(_proposal(0).model_dump(mode="json", exclude={"provider"})))
    adjudicator = AIActionAdjudicator(lambda: valid_provider)
    state = create_initial_state()
    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    proposal = adjudicator.adjudicate_sync(_intent(root_like), state)
    assert proposal.provider.request_id == "provider-request"
    assert valid_provider.calls == 1
    assert '"suggestion_id"' not in valid_provider.prompts[0]
    assert '"visible_context_version"' not in valid_provider.prompts[0]

    duration_payload = _proposal(0).model_dump(mode="json", exclude={"provider"})
    duration_payload.update(
        {
            "duration_candidate": {"unit": "day", "value": 2},
            "duration_reason": "行动需要两日",
        },
    )
    duration_provider = _Provider(json.dumps(duration_payload))
    adjudicator = AIActionAdjudicator(lambda: duration_provider)
    parsed = adjudicator.adjudicate_sync(_intent(root_like), state)
    assert parsed.duration_candidate == Duration(unit="day", value=2)
    assert parsed.duration_reason == "行动需要两日"

    invalid_duration_payload = _proposal(0).model_dump(mode="json", exclude={"provider"})
    invalid_duration_payload["duration_candidate"] = {"unit": "day", "value": 0}
    invalid_duration_payload["duration_reason"] = "非法零时长"
    invalid_duration_provider = _Provider(json.dumps(invalid_duration_payload))
    adjudicator = AIActionAdjudicator(lambda: invalid_duration_provider)
    with pytest.raises(ActionAdjudicationError) as exc_info:
        adjudicator.adjudicate_sync(_intent(root_like), state)
    assert exc_info.value.code == "adjudication_invalid_response"
    assert invalid_duration_provider.calls == 1

    invalid_provider = _Provider("not json")
    adjudicator = AIActionAdjudicator(lambda: invalid_provider)
    with pytest.raises(ActionAdjudicationError) as exc_info:
        adjudicator.adjudicate_sync(_intent(root_like), state)
    assert exc_info.value.code == "adjudication_invalid_response"
    assert invalid_provider.calls == 1

    def _broken_loader():
        raise RuntimeError("provider construction failed")

    adjudicator = AIActionAdjudicator(_broken_loader)
    with pytest.raises(ActionAdjudicationError) as exc_info:
        adjudicator.adjudicate_sync(_intent(root_like), state)
    assert exc_info.value.code == "adjudication_provider_error"


def test_ai_adjudicator_accepts_deepseek_transport_wrapping_but_keeps_schema_strict():
    """DeepSeek may wrap JSON despite response_format=json_object.

    The adapter may remove only that transport wrapper; Pydantic validation
    remains authoritative and no rule/fallback proposal is synthesized.
    """

    class _Provider:
        def __init__(self, text: str):
            self.text = text
            self.calls = 0
            self.prompt = ""
            self.kwargs = None

        async def generate_text_once(self, *args, **kwargs):
            self.calls += 1
            self.prompt = args[0]
            self.kwargs = kwargs
            return GenerationResult(
                text=f"<think>contract check</think>\n```json\n{self.text}\n```",
                provider_request_id="deepseek-request",
            )

    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    provider = _Provider(json.dumps(_proposal(0).model_dump(mode="json", exclude={"provider"})))
    proposal = AIActionAdjudicator(lambda: provider).adjudicate_sync(
        _intent(root_like),
        create_initial_state(),
    )

    assert proposal.duration_candidate is not None
    assert proposal.provider.request_id == "deepseek-request"
    assert provider.calls == 1
    assert provider.kwargs["response_json"] is True
    assert "deltas is optional" in provider.kwargs["system_prompt"]
    assert "duration_candidate" in provider.kwargs["system_prompt"]


def test_ai_adjudicator_rejects_trailing_provider_prose_without_fallback():
    class _Provider:
        async def generate_text_once(self, *_args, **_kwargs):
            payload = json.dumps(_proposal(0).model_dump(mode="json", exclude={"provider"}))
            return GenerationResult(text=f"{payload}\nI also recommend another action.")

    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    with pytest.raises(ActionAdjudicationError) as exc_info:
        AIActionAdjudicator(lambda: _Provider()).adjudicate_sync(
            _intent(root_like),
            create_initial_state(),
        )
    assert exc_info.value.code == "adjudication_invalid_response"


def test_ai_adjudicator_rejects_unrecognized_wrappers_and_spoofed_provider():
    from models.world import new_branch_id, new_game_id, new_version_id

    root_like = SimpleNamespace(
        game_id=new_game_id(),
        branch_id=new_branch_id(),
        version_id=new_version_id(),
    )
    valid = json.dumps(_proposal(0).model_dump(mode="json"))

    class _Provider:
        def __init__(self, text):
            self.text = text

        async def generate_text_once(self, *_args, **_kwargs):
            return GenerationResult(text=self.text)

    for wrapped in (f"leading prose {valid}", f"{valid}```json"):
        with pytest.raises(ActionAdjudicationError) as exc_info:
            AIActionAdjudicator(lambda: _Provider(wrapped)).adjudicate_sync(
                _intent(root_like),
                create_initial_state(),
            )
        assert exc_info.value.code == "adjudication_invalid_response"

    spoofed = json.loads(valid)
    spoofed["provider"] = {"model": "spoofed-model"}
    with pytest.raises(ActionAdjudicationError) as exc_info:
        AIActionAdjudicator(lambda: _Provider(json.dumps(spoofed))).adjudicate_sync(
            _intent(root_like),
            create_initial_state(),
        )
    assert exc_info.value.code == "adjudication_invalid_response"
