from __future__ import annotations

import pytest

from api.action_service import ActionService
from db import saves, worlds
from engine.lifecycle import DefaultLifecyclePlanner
from engine.settlement import SettlementValidationError, apply_world_deltas
from models.game import create_initial_state
from models.settlement import (
    ActionIntent,
    AdjudicationProposal,
    LifecycleWorldDelta,
    MetricWorldDelta,
)
from models.world import Duration, PlayerWorldStatus, new_client_action_id, new_delta_id


def _delta(
    goal_id: str,
    next_status: str,
    *,
    before_status: str | None = None,
) -> LifecycleWorldDelta:
    return LifecycleWorldDelta(
        delta_id=new_delta_id(),
        transition_type="goal",
        transition_id=goal_id,
        before_status=before_status,
        next_status=next_status,
    )


def test_goal_available_and_active_transitions_are_idempotent() -> None:
    state = create_initial_state()
    first = apply_world_deltas(state, [_delta("continuity", "available")])
    second = apply_world_deltas(first, [_delta("continuity", "active", before_status="available")])

    assert first.player_world_status.actionable_goal_ids == ["continuity"]
    assert second.player_world_status.actionable_goal_ids == ["continuity"]


@pytest.mark.parametrize("next_status", ["completed", "blocked", "ended"])
def test_goal_terminal_transitions_remove_visible_goal(next_status: str) -> None:
    state = create_initial_state().model_copy(
        update={
            "player_world_status": PlayerWorldStatus(
                actionable_goal_ids=["continuity", "other-goal"],
            ),
        },
    )
    changed = apply_world_deltas(
        state,
        [_delta("continuity", next_status, before_status="active")],
    )

    assert changed.player_world_status.actionable_goal_ids == ["other-goal"]


def test_goal_before_status_conflict_is_stable_and_state_is_unchanged() -> None:
    state = create_initial_state()
    delta = _delta("continuity", "completed", before_status="active")

    with pytest.raises(SettlementValidationError) as exc_info:
        apply_world_deltas(state, [delta])

    assert exc_info.value.code == "lifecycle_goal_precondition_failed"
    assert state.player_world_status.actionable_goal_ids == []


def test_dead_player_cannot_receive_new_goal() -> None:
    state = create_initial_state().model_copy(
        update={
            "player_world_status": PlayerWorldStatus(
                life_status="dead",
                terminal_settlement_id="00000000-0000-0000-0000-000000000001",
                terminal_version_id="00000000-0000-0000-0000-000000000002",
            ),
        },
    )

    with pytest.raises(SettlementValidationError) as exc_info:
        apply_world_deltas(state, [_delta("continuity", "available")])

    assert exc_info.value.code == "dead_player_goal_transition"
    assert state.player_world_status.actionable_goal_ids == []


class _StaticAdjudicator:
    def __init__(self, proposal: AdjudicationProposal):
        self.proposal = proposal

    async def adjudicate(self, _intent: ActionIntent, _state):
        return self.proposal


def test_default_lifecycle_planner_commits_continuity_goal(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "lifecycle-action.db")
    saves.init_db()
    root = worlds.create_game_with_root(create_initial_state())
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="观察局势",
        action_kind="wait",
        mode="life_story",
    )
    proposal = AdjudicationProposal(
        result_tier="success",
        key_factors=["行动推动了当前世界"],
        immediate_changes=["等待一小时"],
        execution_status="completed",
        duration_candidate=Duration(unit="hour", value=1),
        duration_reason="观察一小时",
        deltas=[
            MetricWorldDelta(
                delta_id=new_delta_id(),
                target_scope="world",
                field="consecutive_waits",
                operation="increment",
                before_value=0,
                value=1,
            ),
        ],
    )

    execution = ActionService(
        adjudicator=_StaticAdjudicator(proposal),
        lifecycle_planner=DefaultLifecyclePlanner(),
    ).execute_sync(intent)

    assert execution.state.player_world_status.life_status == "alive"
    assert execution.state.player_world_status.actionable_goal_ids == [
        "world_continuity_required",
    ]
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
