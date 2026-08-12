from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.action_routes import set_action_service_for_testing
from api.action_service import ActionService
from db import saves, worlds
from engine.settlement import SettlementValidationError
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    ActivityCandidate,
    ActivityCheckpointDecision,
    EntityWorldDelta,
    FieldChange,
    MetricWorldDelta,
)
from models.world import (
    Duration,
    EntitySource,
    PersonEntity,
    new_client_action_id,
    new_delta_id,
    new_entity_id,
)
from main import app


class _QueueAdjudicator:
    def __init__(self, *proposals: AdjudicationProposal):
        self.proposals = list(proposals)
        self.calls = 0

    async def adjudicate(self, _intent, _state):
        self.calls += 1
        if not self.proposals:
            raise AssertionError("unexpected adjudication call")
        return self.proposals.pop(0)


class _AutoCompleteActivityAdjudicator:
    def __init__(self, creation: AdjudicationProposal):
        self.creation = creation
        self.calls = 0

    async def adjudicate(self, intent, state):
        self.calls += 1
        if intent.activity_command is None:
            return self.creation
        activity = next(item for item in state.activities if item.activity_id == intent.activity_id)
        checkpoint = next(item for item in activity.checkpoints if item.status == "pending")
        terminal = checkpoint.planned_end.absolute_hour == activity.planned_end.absolute_hour
        return AdjudicationProposal(
            result_tier="success",
            immediate_changes=["抵达目的地" if terminal else "完成普通时间检查点"],
            execution_status="completed" if terminal else "attempted",
            activity_decision=ActivityCheckpointDecision(
                transition="complete" if terminal else "continue",
                reason="计划终点已到达" if terminal else "世界状态允许自动继续",
            ),
        )


def _store(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "activities.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    return worlds.load_version(root.version_id).state, root


def _create_intent(root, *, text: str = "率队远行四十日") -> ActionIntent:
    return ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text=text,
        action_kind="travel",
        mode="governance",
    )


def _creation_proposal(*, days: int = 40) -> AdjudicationProposal:
    return AdjudicationProposal(
        result_tier="success",
        immediate_changes=["远行计划已建立"],
        execution_status="attempted",
        duration_candidate=Duration(unit="day", value=days),
        duration_reason="路程、补给与队伍规模需要分段推进",
        activity_candidate=ActivityCandidate(
            kind="travel",
            target_summary="北上大都",
            prerequisites=["执行者仍可行动", "道路可通行"],
            planned_effects=["抵达后才确认结果"],
            checkpoint_horizon_hours=720,
        ),
    )


def _checkpoint_intent(execution, *, command: str = "continue", **updates) -> ActionIntent:
    activity = execution.state.activities[0]
    checkpoint = next(
        item for item in activity.checkpoints if item.status == "pending"
    )
    payload = {
        "game_id": execution.result.version.game_id,
        "branch_id": execution.result.version.branch_id,
        "expected_parent_version_id": execution.result.version.version_id,
        "client_action_id": (
            checkpoint.client_action_id
            if command == "continue"
            else new_client_action_id()
        ),
        "raw_text": f"活动命令：{command}",
        "action_kind": "activity_checkpoint",
        "mode": "governance",
        "activity_id": activity.activity_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_sequence": checkpoint.sequence,
        "activity_command": command,
    }
    payload.update(updates)
    return ActionIntent(**payload)


def test_activity_creation_commits_plan_without_time_or_final_effect(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    adjudicator = _QueueAdjudicator(_creation_proposal())

    created = ActionService(adjudicator=adjudicator).execute_sync(_create_intent(root))

    assert created.state.time.clock == initial.time.clock
    assert len(created.state.activities) == 1
    activity = created.state.activities[0]
    assert activity.status == "in_progress"
    assert activity.elapsed_hours == 0
    assert activity.remaining_hours == 40 * 24
    assert activity.planned_effects == ["抵达后才确认结果"]
    assert activity.committed_segment_effects == []
    assert len(activity.checkpoints) == 1
    assert activity.checkpoints[0].expected_parent_version_id == created.result.version.version_id
    assert created.result.facts.activity_id == activity.activity_id
    assert created.result.facts.time_plan is None
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1


def test_forty_day_activity_uses_two_checkpoint_versions_and_finishes_once(
    monkeypatch,
    tmp_path,
):
    _, root = _store(monkeypatch, tmp_path)
    adjudicator = _QueueAdjudicator(
        _creation_proposal(),
        AdjudicationProposal(
            result_tier="success",
            immediate_changes=["完成第一段行程"],
            execution_status="attempted",
            activity_decision=ActivityCheckpointDecision(
                transition="continue",
                reason="道路正常，自动继续",
            ),
        ),
        AdjudicationProposal(
            result_tier="success",
            immediate_changes=["抵达目的地"],
            execution_status="completed",
            activity_decision=ActivityCheckpointDecision(
                transition="complete",
                reason="已抵达大都",
            ),
        ),
    )
    service = ActionService(adjudicator=adjudicator)

    created = service.execute_sync(_create_intent(root))
    first = service.execute_sync(_checkpoint_intent(created))
    completed = service.execute_sync(_checkpoint_intent(first))

    activity = completed.state.activities[0]
    assert activity.status == "completed"
    assert activity.next_checkpoint_id is None
    assert activity.elapsed_hours == 40 * 24
    assert activity.remaining_hours == 0
    assert [item.status for item in activity.checkpoints] == ["completed", "completed"]
    assert all(item.settlement_id and item.version_id for item in activity.checkpoints)
    assert all(item.roll_key is None and item.roll_value is None for item in activity.checkpoints)
    assert completed.result.facts.activity_status == "completed"
    assert completed.result.facts.checkpoint_sequence == 2
    assert completed.result.facts.time_plan is not None
    assert adjudicator.calls == 3
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 3
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 4


@pytest.mark.parametrize(
    "duration,minimum_checkpoints",
    [
        (Duration(unit="month", value=3), 3),
        (Duration(unit="year", value=2), 24),
    ],
)
def test_long_activity_processes_every_month_boundary_as_one_checkpoint_version(
    monkeypatch,
    tmp_path,
    duration,
    minimum_checkpoints,
):
    initial, root = _store(monkeypatch, tmp_path)
    creation = _creation_proposal(days=1).model_copy(
        update={"duration_candidate": duration},
    )
    adjudicator = _AutoCompleteActivityAdjudicator(creation)
    service = ActionService(adjudicator=adjudicator)

    execution = service.execute_sync(
        _create_intent(root, text=f"执行长期活动：{duration.value}{duration.unit}"),
    )
    checkpoint_count = 0
    while execution.state.activities[0].status == "in_progress":
        execution = service.execute_sync(_checkpoint_intent(execution))
        checkpoint_count += 1
        assert checkpoint_count < 40

    activity = execution.state.activities[0]
    settlements = worlds.list_settlements(root.game_id, root.branch_id)
    versions = worlds.list_versions(root.game_id, root.branch_id)
    month_invocations = sum(
        invocation.boundary_kind == "month"
        for settlement in settlements
        if settlement.time_plan is not None
        for invocation in settlement.time_plan.consumer_invocations
    )

    assert activity.status == "completed"
    assert activity.elapsed_hours == activity.planned_elapsed_hours
    assert activity.remaining_hours == 0
    assert execution.state.time.clock.absolute_hour == (
        initial.time.clock.absolute_hour + activity.planned_elapsed_hours
    )
    assert checkpoint_count >= minimum_checkpoints
    assert month_invocations == checkpoint_count
    assert len(settlements) == checkpoint_count + 1
    assert len(versions) == checkpoint_count + 2
    assert all(item.status == "completed" for item in activity.checkpoints)
    assert all(item.roll_key is None and item.roll_value is None for item in activity.checkpoints)
    assert activity.committed_segment_effects[-1] == "抵达目的地"


def test_external_executor_loss_rebases_checkpoint_and_requires_reassignment(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "executor-loss.db")
    saves.init_db()
    state = create_initial_state()
    executor_id = new_entity_id()
    replacement_id = new_entity_id()
    state.entity_registry[executor_id] = PersonEntity(
        entity_id=executor_id,
        display_name="主执行者",
        source=EntitySource(kind="system", summary="test executor"),
    )
    state.entity_registry[replacement_id] = PersonEntity(
        entity_id=replacement_id,
        display_name="替补执行者",
        source=EntitySource(kind="system", summary="test replacement"),
    )
    root = worlds.create_game_with_root(state)
    creation = _creation_proposal(days=1).model_copy(
        update={
            "requested_executor_id": executor_id,
            "actual_executor_id": executor_id,
        },
    )
    creator = ActionService(adjudicator=_QueueAdjudicator(creation))
    create_intent = _create_intent(root, text="由主执行者押运一日")
    create_intent = create_intent.model_copy(
        update={"requested_executor_id": executor_id},
    )
    created = creator.execute_sync(create_intent)

    executor_loss = AdjudicationProposal(
        result_tier="success",
        execution_status="completed",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="确认执行者失联并调整活动需要一小时",
        deltas=[
            EntityWorldDelta(
                delta_id=new_delta_id(),
                operation="update",
                target_entity_id=executor_id,
                changes=[
                    FieldChange(
                        field="available",
                        before_value=True,
                        value=False,
                    ),
                ],
            ),
        ],
    )
    loss_service = ActionService(adjudicator=_QueueAdjudicator(executor_loss))
    lost = loss_service.execute_sync(
        ActionIntent(
            game_id=root.game_id,
            branch_id=root.branch_id,
            expected_parent_version_id=created.result.version.version_id,
            client_action_id=new_client_action_id(),
            raw_text="途中消息确认主执行者已失联",
            action_kind="event",
        ),
    )
    pending = next(
        item for item in lost.state.activities[0].checkpoints if item.status == "pending"
    )
    assert pending.expected_parent_version_id == lost.result.version.version_id

    checkpoint_adjudicator = _QueueAdjudicator(
        AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            activity_decision=ActivityCheckpointDecision(
                transition="complete",
                reason="完成押运",
            ),
        ),
    )
    checkpoint_service = ActionService(adjudicator=checkpoint_adjudicator)
    with pytest.raises(SettlementValidationError) as exc_info:
        checkpoint_service.execute_sync(_checkpoint_intent(lost))
    assert exc_info.value.code == "activity_executor_unavailable"
    assert checkpoint_adjudicator.calls == 0
    assert worlds.load_branch_head(root.game_id, root.branch_id).ref == lost.result.version

    reassigned = checkpoint_service.execute_sync(
        _checkpoint_intent(
            lost,
            command="reassign",
            replacement_executor_id=replacement_id,
        ),
    )
    assert reassigned.state.activities[0].actual_executor_id == replacement_id
    completed = checkpoint_service.execute_sync(_checkpoint_intent(reassigned))
    assert completed.state.activities[0].status == "completed"
    assert completed.state.activities[0].elapsed_hours == 24
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 4
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 5


def test_external_action_cannot_skip_a_pending_activity_checkpoint(monkeypatch, tmp_path):
    initial, root = _store(monkeypatch, tmp_path)
    creator = ActionService(adjudicator=_QueueAdjudicator(_creation_proposal(days=1)))
    created = creator.execute_sync(_create_intent(root))
    external = AdjudicationProposal(
        result_tier="success",
        execution_status="completed",
        duration_candidate=Duration(unit="day", value=1),
        duration_reason="外部行动也需要整整一日",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="consecutive_waits",
                operation="increment",
                before_value=initial.consecutive_waits,
                value=1,
            ),
        ],
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        ActionService(adjudicator=_QueueAdjudicator(external)).execute_sync(
            ActionIntent(
                game_id=root.game_id,
                branch_id=root.branch_id,
                expected_parent_version_id=created.result.version.version_id,
                client_action_id=new_client_action_id(),
                raw_text="处理另一项耗时一日的行动",
                action_kind="wait",
            ),
        )

    assert exc_info.value.code == "activity_checkpoint_due"
    head = worlds.load_branch_head(root.game_id, root.branch_id)
    assert head.ref == created.result.version
    assert head.state == created.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_material_checkpoint_pauses_for_redirect_then_resumes(monkeypatch, tmp_path):
    _, root = _store(monkeypatch, tmp_path)
    adjudicator = _QueueAdjudicator(
        _creation_proposal(),
        AdjudicationProposal(
            result_tier="partial_success",
            execution_status="blocked",
            activity_decision=ActivityCheckpointDecision(
                transition="await_player",
                reason="前路断绝，需要改道",
                interruption_facts=["道路中断"],
                pending_decision={
                    "decision_type": "redirect",
                    "reason": "选择新的行军路线",
                    "options": ["绕道徐州", "终止远行"],
                    "facts": ["道路中断"],
                },
            ),
        ),
        AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            activity_decision=ActivityCheckpointDecision(
                transition="complete",
                reason="改道后完成行程",
            ),
        ),
    )
    service = ActionService(adjudicator=adjudicator)
    created = service.execute_sync(_create_intent(root))
    awaiting = service.execute_sync(_checkpoint_intent(created))
    assert awaiting.state.activities[0].status == "awaiting_player_decision"

    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(_checkpoint_intent(awaiting))
    assert exc_info.value.code == "activity_player_decision_required"

    redirected = service.execute_sync(
        _checkpoint_intent(
            awaiting,
            command="redirect",
            redirect_text="改走徐州北上",
        ),
    )
    activity = redirected.state.activities[0]
    assert activity.status == "in_progress"
    assert activity.intent == "改走徐州北上"
    pending = next(item for item in activity.checkpoints if item.status == "pending")
    assert pending.expected_parent_version_id == redirected.result.version.version_id

    completed = service.execute_sync(_checkpoint_intent(redirected))
    assert completed.state.activities[0].status == "completed"
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 4
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 5


def test_failed_checkpoint_commits_once_and_same_identity_replays(monkeypatch, tmp_path):
    _, root = _store(monkeypatch, tmp_path)
    service = ActionService(
        adjudicator=_QueueAdjudicator(
            _creation_proposal(days=1),
            AdjudicationProposal(
                result_tier="failure",
                immediate_changes=["已发生的途中损耗被保留"],
                execution_status="failed",
                activity_decision=ActivityCheckpointDecision(
                    transition="fail",
                    reason="补给耗尽，活动终止",
                    interruption_facts=["资源不足"],
                ),
            ),
        ),
    )
    created = service.execute_sync(_create_intent(root))
    checkpoint_intent = _checkpoint_intent(created)

    failed = service.execute_sync(checkpoint_intent)
    replayed = service.execute_sync(checkpoint_intent)

    activity = failed.state.activities[0]
    assert activity.status == "failed"
    assert activity.next_checkpoint_id is None
    assert activity.interruption_facts == ["资源不足"]
    assert replayed.result.replayed is True
    assert replayed.result.version == failed.result.version
    assert replayed.state == failed.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 2
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 3


def test_pause_resume_cancel_each_commit_once_and_terminal_retry_is_noop(
    monkeypatch,
    tmp_path,
):
    initial, root = _store(monkeypatch, tmp_path)
    service = ActionService(adjudicator=_QueueAdjudicator(_creation_proposal()))
    created = service.execute_sync(_create_intent(root))
    paused = service.execute_sync(_checkpoint_intent(created, command="pause"))
    assert paused.state.activities[0].status == "paused"
    paused_activity = paused.state.activities[0]
    paused_end = paused_activity.planned_end.absolute_hour
    paused_remaining = paused_activity.remaining_hours

    external = ActionService(
        adjudicator=_QueueAdjudicator(
            AdjudicationProposal(
                result_tier="success",
                execution_status="completed",
                duration_candidate=Duration(unit="hour", value=1),
                duration_reason="暂停期间处理另一项一小时行动",
                deltas=[
                    MetricWorldDelta(
                        delta_id=new_delta_id(),
                        target_scope="world",
                        field="consecutive_waits",
                        operation="increment",
                        before_value=initial.consecutive_waits,
                        value=1,
                    ),
                ],
            ),
        ),
    ).execute_sync(
        ActionIntent(
            game_id=root.game_id,
            branch_id=root.branch_id,
            expected_parent_version_id=paused.result.version.version_id,
            client_action_id=new_client_action_id(),
            raw_text="活动暂停时处理其他事务",
            action_kind="wait",
        ),
    )
    shifted = external.state.activities[0]
    shifted_checkpoint = next(item for item in shifted.checkpoints if item.status == "pending")
    assert shifted.status == "paused"
    assert shifted.elapsed_hours == 0
    assert shifted.remaining_hours == paused_remaining
    assert shifted.planned_end.absolute_hour == paused_end + 1
    assert (
        shifted_checkpoint.planned_start.absolute_hour
        == external.state.time.clock.absolute_hour
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(_checkpoint_intent(external))
    assert exc_info.value.code == "activity_player_decision_required"

    resumed = service.execute_sync(_checkpoint_intent(external, command="resume"))
    assert resumed.state.activities[0].status == "in_progress"
    cancelled = service.execute_sync(_checkpoint_intent(resumed, command="cancel"))
    assert cancelled.state.activities[0].status == "cancelled"
    assert cancelled.state.activities[0].next_checkpoint_id is None

    with pytest.raises((SettlementValidationError, worlds.StaleParentVersionError)) as exc_info:
        service.execute_sync(_checkpoint_intent(resumed, command="cancel"))
    assert exc_info.value.code in {"stale_parent_version", "stale_activity_checkpoint"}
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 5
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 6


def test_bounded_batch_auto_continues_ordinary_checkpoints(monkeypatch, tmp_path):
    _, root = _store(monkeypatch, tmp_path)
    adjudicator = _QueueAdjudicator(
        _creation_proposal(),
        AdjudicationProposal(
            result_tier="success",
            execution_status="attempted",
            activity_decision=ActivityCheckpointDecision(
                transition="continue",
                reason="普通检查点自动继续",
            ),
        ),
        AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            activity_decision=ActivityCheckpointDecision(
                transition="complete",
                reason="活动完成",
            ),
        ),
    )
    service = ActionService(adjudicator=adjudicator)
    created = service.execute_sync(_create_intent(root))
    activity = created.state.activities[0]

    batch = service.continue_activity_batch_sync(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=created.result.version.version_id,
        activity_id=activity.activity_id,
        max_checkpoints=4,
    )

    assert len(batch.results) == 2
    assert batch.activity.status == "completed"
    assert batch.processing is False
    assert batch.continuation_cursor is None
    assert adjudicator.calls == 3


def test_fork_preserves_clock_and_activity_but_rebases_pending_checkpoint(
    monkeypatch,
    tmp_path,
):
    _, root = _store(monkeypatch, tmp_path)
    creator = ActionService(adjudicator=_QueueAdjudicator(_creation_proposal()))
    created = creator.execute_sync(_create_intent(root))
    original_clock = created.state.time.clock

    fork_ref = worlds.create_branch_from_version(created.result.version.version_id)
    fork = worlds.load_branch_head(root.game_id, fork_ref.branch_id)
    fork_activity = fork.state.activities[0]
    pending = next(
        checkpoint for checkpoint in fork_activity.checkpoints if checkpoint.status == "pending"
    )

    assert fork.state.time.clock == original_clock
    assert fork.state.time.calendar == created.state.time.calendar
    assert fork.state.world_metadata.calendar_schema_version == "yuanming-calendar-v1"
    assert fork.state.world_metadata.source_kind == "fork"
    assert pending.expected_parent_version_id == fork_ref.version_id
    assert worlds.load_branch_head(root.game_id, root.branch_id).ref == created.result.version

    service = ActionService(
        adjudicator=_QueueAdjudicator(
            AdjudicationProposal(
                result_tier="success",
                execution_status="attempted",
                activity_decision=ActivityCheckpointDecision(
                    transition="continue",
                    reason="分支上的普通检查点继续",
                ),
            ),
        ),
    )
    advanced_fork = service.execute_sync(
        ActionIntent(
            game_id=root.game_id,
            branch_id=fork_ref.branch_id,
            expected_parent_version_id=fork_ref.version_id,
            client_action_id=pending.client_action_id,
            raw_text="在新世界线继续活动",
            action_kind="activity_checkpoint",
            activity_id=fork_activity.activity_id,
            checkpoint_id=pending.checkpoint_id,
            checkpoint_sequence=pending.sequence,
            activity_command="continue",
        ),
    )
    assert advanced_fork.state.time.clock.absolute_hour > original_clock.absolute_hour
    assert worlds.load_branch_head(root.game_id, root.branch_id).state.time.clock == original_clock


def test_activity_http_query_continue_and_publish_recovery(monkeypatch, tmp_path):
    _, root = _store(monkeypatch, tmp_path)
    service = ActionService(
        adjudicator=_QueueAdjudicator(
            _creation_proposal(days=1),
            AdjudicationProposal(
                result_tier="success",
                execution_status="completed",
                activity_decision=ActivityCheckpointDecision(
                    transition="complete",
                    reason="HTTP 检查点完成",
                ),
            ),
        ),
    )
    created = service.execute_sync(_create_intent(root))
    activity = created.state.activities[0]
    client = TestClient(app)
    set_action_service_for_testing(service)

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("injected publish failure")

    monkeypatch.setattr("api.action_routes._publish_world_head", fail_publish)
    try:
        queried = client.get(
            f"/api/activities/{root.game_id}/{root.branch_id}/{activity.activity_id}",
        )
        assert queried.status_code == 200
        assert queried.json()["activity_id"] == str(activity.activity_id)

        continued = client.post(
            f"/api/activities/{activity.activity_id}/continue",
            json={
                "game_id": str(root.game_id),
                "branch_id": str(root.branch_id),
                "expected_parent_version_id": str(created.result.version.version_id),
                "max_checkpoints": 1,
            },
        )
    finally:
        set_action_service_for_testing(None)

    assert continued.status_code == 200
    payload = continued.json()
    assert payload["activity"]["status"] == "completed"
    assert payload["activity"] == payload["state"]["activities"][0]
    assert payload["results"][0]["facts"]["checkpoint_sequence"] == 1
    assert payload["narrative"]["settlement_id"] == payload["results"][0]["facts"]["settlement_id"]
    assert payload["narrative"]["narrative_status"] in {
        "validated",
        "repaired",
        "sanitized",
        "fallback_facts",
    }
