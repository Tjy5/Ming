from __future__ import annotations

import pytest

from api.action_service import ActionAdjudicationError, ActionService
from db import saves, worlds
from engine.calendar import advance_game_time
from engine.clock import ClockConsumerRegistry, ClockPlanningError
from engine.settlement import SettlementValidationError
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    ActivityCandidate,
    ActivityCheckpointDecision,
)
from models.world import Duration, new_client_action_id


class _MutableAdjudicator:
    def __init__(self, proposal):
        self.proposal = proposal
        self.fail = False
        self.calls = 0

    async def adjudicate(self, _intent, _state):
        self.calls += 1
        if self.fail:
            raise ActionAdjudicationError(
                "adjudication_provider_error",
                "injected checkpoint failure",
            )
        return self.proposal


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "checkpoint.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    create_proposal = AdjudicationProposal(
        result_tier="success",
        execution_status="attempted",
        duration_candidate=Duration(unit="day", value=40),
        duration_reason="长途活动需要检查点",
        activity_candidate=ActivityCandidate(kind="travel"),
    )
    creator = _MutableAdjudicator(create_proposal)
    service = ActionService(adjudicator=creator)
    created = service.execute_sync(
        ActionIntent(
            game_id=root.game_id,
            branch_id=root.branch_id,
            expected_parent_version_id=root.version_id,
            client_action_id=new_client_action_id(),
            raw_text="远行四十日",
            action_kind="travel",
        ),
    )
    activity = created.state.activities[0]
    checkpoint = activity.checkpoints[0]
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=created.result.version.version_id,
        client_action_id=checkpoint.client_action_id,
        raw_text="自动继续活动检查点",
        action_kind="activity_checkpoint",
        activity_id=activity.activity_id,
        checkpoint_id=checkpoint.checkpoint_id,
        checkpoint_sequence=checkpoint.sequence,
        activity_command="continue",
    )
    return root, created, intent


def _continue_proposal():
    return AdjudicationProposal(
        result_tier="success",
        execution_status="attempted",
        activity_decision=ActivityCheckpointDecision(
            transition="continue",
            reason="普通检查点自动继续",
        ),
    )


def _assert_checkpoint_unchanged(root, created):
    head = worlds.load_branch_head(root.game_id, root.branch_id)
    assert head.ref == created.result.version
    assert head.state == created.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_checkpoint_failure_discards_projection_and_retry_reuses_identity(
    monkeypatch,
    tmp_path,
):
    root, created, intent = _setup(monkeypatch, tmp_path)
    adjudicator = _MutableAdjudicator(_continue_proposal())
    adjudicator.fail = True
    service = ActionService(adjudicator=adjudicator)

    with pytest.raises(ActionAdjudicationError):
        service.execute_sync(intent)

    unchanged = worlds.load_branch_head(root.game_id, root.branch_id)
    assert unchanged.ref == created.result.version
    assert unchanged.state.time.clock == created.state.time.clock
    pending = unchanged.state.activities[0].checkpoints[0]
    assert pending.status == "pending"
    assert pending.client_action_id == intent.client_action_id

    adjudicator.fail = False
    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)
    assert committed.result.replayed is False
    assert replayed.result.replayed is True
    assert replayed.state == committed.state
    assert adjudicator.calls == 2
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 2


def test_checkpoint_storage_failure_rolls_back_time_activity_and_version(
    monkeypatch,
    tmp_path,
):
    root, created, intent = _setup(monkeypatch, tmp_path)
    service = ActionService(adjudicator=_MutableAdjudicator(_continue_proposal()))
    original_insert_version = worlds._insert_version

    def fail_checkpoint_version(*args, **kwargs):
        ref = kwargs.get("ref")
        if ref is not None and ref.parent_version_id == created.result.version.version_id:
            raise worlds.WorldStorageError()
        return original_insert_version(*args, **kwargs)

    monkeypatch.setattr(worlds, "_insert_version", fail_checkpoint_version)
    with pytest.raises(worlds.WorldStorageError):
        service.execute_sync(intent)

    head = worlds.load_branch_head(root.game_id, root.branch_id)
    assert head.ref == created.result.version
    assert head.state == created.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2


def test_checkpoint_planner_failure_is_zero_write_and_retryable(monkeypatch, tmp_path):
    root, created, intent = _setup(monkeypatch, tmp_path)
    adjudicator = _MutableAdjudicator(_continue_proposal())
    service = ActionService(adjudicator=adjudicator)

    def fail_plan(*_args, **_kwargs):
        raise ClockPlanningError("injected_plan_failure", "injected checkpoint plan failure")

    monkeypatch.setattr("api.action_service.plan_checkpoint", fail_plan)
    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(intent)

    assert exc_info.value.code == "injected_plan_failure"
    assert adjudicator.calls == 0
    _assert_checkpoint_unchanged(root, created)


def test_checkpoint_consumer_failure_discards_projection(monkeypatch, tmp_path):
    class _FailingMonthConsumer:
        name = "failing-month-consumer"
        version = "1"
        order = 1
        boundary_kinds = frozenset({"month"})

        def consume(self, **_kwargs):
            raise ValueError("injected consumer failure")

    root, created, intent = _setup(monkeypatch, tmp_path)
    adjudicator = _MutableAdjudicator(_continue_proposal())
    service = ActionService(
        adjudicator=adjudicator,
        clock_registry=ClockConsumerRegistry([_FailingMonthConsumer()]),
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(intent)

    assert exc_info.value.code == "invalid_clock_consumer_result"
    assert adjudicator.calls == 0
    _assert_checkpoint_unchanged(root, created)


def test_checkpoint_final_validation_failure_discards_projection(monkeypatch, tmp_path):
    class _InvalidIdentityApplier:
        def apply_world_deltas(self, state, _deltas, time_plan):
            changed = state.model_copy(deep=True)
            advance_game_time(changed.time, time_plan.normalized_duration.duration)
            changed.world_metadata = changed.world_metadata.model_copy(
                update={"source_ref": "injected-invalid-final-state"},
            )
            return changed

    root, created, intent = _setup(monkeypatch, tmp_path)
    adjudicator = _MutableAdjudicator(_continue_proposal())
    service = ActionService(
        adjudicator=adjudicator,
        world_state_applier=_InvalidIdentityApplier(),
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        service.execute_sync(intent)

    assert exc_info.value.code == "world_identity_mutation"
    assert adjudicator.calls == 1
    _assert_checkpoint_unchanged(root, created)


def test_risky_checkpoint_roll_is_public_persisted_and_retry_stable(monkeypatch, tmp_path):
    root, created, intent = _setup(monkeypatch, tmp_path)
    proposal = AdjudicationProposal(
        result_tier="partial_success",
        execution_status="attempted",
        uncertainty=0.8,
        activity_decision=ActivityCheckpointDecision(
            transition="continue",
            reason="危险路段已经通过，活动继续",
        ),
    )
    adjudicator = _MutableAdjudicator(proposal)
    service = ActionService(adjudicator=adjudicator)

    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)
    checkpoint = committed.state.activities[0].checkpoints[0]
    replayed_checkpoint = replayed.state.activities[0].checkpoints[0]

    assert checkpoint.roll_key is not None
    assert len(checkpoint.roll_key) == 64
    assert 1 <= checkpoint.roll_value <= 100
    assert replayed_checkpoint.roll_key == checkpoint.roll_key
    assert replayed_checkpoint.roll_value == checkpoint.roll_value
    assert replayed.result.replayed is True
    assert adjudicator.calls == 1
