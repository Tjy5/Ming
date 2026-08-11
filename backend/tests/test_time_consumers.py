from __future__ import annotations

from api.action_service import ActionService
from db import saves, worlds
from engine.calendar import set_game_time_projection
from engine.settlement import ELAPSED_PATCH_FIELDS
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, ElapsedStatePatchDelta
from models.world import Duration, new_client_action_id


class _DurationAdjudicator:
    def __init__(self, durations: list[Duration]):
        self._durations = list(durations)
        self.calls = 0

    async def adjudicate(self, _intent, _state):
        self.calls += 1
        duration = self._durations.pop(0)
        return AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            duration_candidate=duration,
            duration_reason="测试实际经过时间",
        )


def _root(monkeypatch, tmp_path, name: str):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / name)
    saves.init_db()
    state = create_initial_state()
    state.phase = "governance"
    set_game_time_projection(
        state.time,
        year=1356,
        month=3,
        migration_source="initial_world",
    )
    return worlds.create_game_with_root(state)


def _run(root, durations: list[Duration]):
    service = ActionService(adjudicator=_DurationAdjudicator(durations))
    parent = root.version_id
    executions = []
    for duration in durations:
        execution = service.execute_sync(
            ActionIntent(
                game_id=root.game_id,
                branch_id=root.branch_id,
                expected_parent_version_id=parent,
                client_action_id=new_client_action_id(),
                raw_text=f"等待 {duration.value} {duration.unit}",
                action_kind="wait",
            ),
        )
        executions.append(execution)
        parent = execution.result.version.version_id
    return executions


def _gameplay_projection(state):
    payload = state.model_dump(mode="json")
    return {
        "time": payload["time"],
        **{field: payload[field] for field in sorted(ELAPSED_PATCH_FIELDS)},
    }


def test_short_actions_inside_month_do_not_repeat_monthly_drift(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path, "short-actions.db")
    initial = worlds.load_version(root.version_id).state

    executions = _run(root, [Duration(unit="hour", value=1) for _ in range(10)])
    final = executions[-1].state

    assert final.time.clock.absolute_hour == initial.time.clock.absolute_hour + 10
    assert final.decree_count == initial.decree_count
    assert final.national_treasury == initial.national_treasury
    assert final.grain == initial.grain
    assert all(not item.result.facts.time_plan.consumer_invocations for item in executions)
    assert all(
        not any(isinstance(delta, ElapsedStatePatchDelta) for delta in item.result.facts.deltas)
        for item in executions
    )


def test_equal_elapsed_time_split_differently_has_identical_monthly_effects(
    monkeypatch,
    tmp_path,
):
    one_root = _root(monkeypatch, tmp_path, "one-segment.db")
    one = _run(one_root, [Duration(unit="day", value=30)])[-1]

    split_root = worlds.create_game_with_root(
        worlds.load_version(one_root.version_id).state.model_copy(deep=True),
    )
    split = _run(split_root, [Duration(unit="day", value=1) for _ in range(30)])

    assert _gameplay_projection(one.state) == _gameplay_projection(split[-1].state)
    assert sum(
        len(item.result.facts.time_plan.consumer_invocations) for item in split
    ) == len(one.result.facts.time_plan.consumer_invocations) == 1
    assert sum(
        isinstance(delta, ElapsedStatePatchDelta)
        for item in split
        for delta in item.result.facts.deltas
    ) == 1
    assert sum(
        isinstance(delta, ElapsedStatePatchDelta)
        for delta in one.result.facts.deltas
    ) == 1


def test_multiple_month_boundaries_chain_consumer_patch_preconditions(
    monkeypatch,
    tmp_path,
):
    one_root = _root(monkeypatch, tmp_path, "multi-month-segment.db")
    initial = worlds.load_version(one_root.version_id).state
    split_root = worlds.create_game_with_root(initial.model_copy(deep=True))

    one = _run(one_root, [Duration(unit="month", value=2)])[-1]
    split = _run(
        split_root,
        [Duration(unit="month", value=1), Duration(unit="month", value=1)],
    )[-1]

    assert _gameplay_projection(one.state) == _gameplay_projection(split.state)
    assert len(one.result.facts.time_plan.consumer_invocations) == 2
    assert sum(
        isinstance(delta, ElapsedStatePatchDelta)
        for delta in one.result.facts.deltas
    ) == 2


def test_month_consumer_facts_replay_without_reapplying_effects(monkeypatch, tmp_path):
    root = _root(monkeypatch, tmp_path, "consumer-replay.db")
    action_id = new_client_action_id()
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=action_id,
        raw_text="等待三十日",
        action_kind="wait",
    )
    adjudicator = _DurationAdjudicator([Duration(unit="day", value=30)])
    service = ActionService(adjudicator=adjudicator)

    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)

    assert replayed.result.replayed is True
    assert replayed.state == committed.state
    assert adjudicator.calls == 1
    assert len(committed.result.facts.time_plan.consumer_invocations) == 1
    patch = [
        delta
        for delta in committed.result.facts.deltas
        if isinstance(delta, ElapsedStatePatchDelta)
    ]
    assert len(patch) == 1
    assert patch[0].handler_name == "legacy-world-state-monthly"
    assert len(worlds.list_versions(root.game_id, root.branch_id)) == 2
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
