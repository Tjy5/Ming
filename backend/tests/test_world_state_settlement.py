from __future__ import annotations

from uuid import uuid4

from api.action_service import ActionService
from db import saves, worlds
from models.enums import MinisterStatus
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, MetricWorldDelta
from models.world import DeltaId, Duration, PersonEntity, new_client_action_id


class _Adjudicator:
    def __init__(self, executor_id):
        self.executor_id = executor_id
        self.calls = 0

    async def adjudicate(self, intent, state):
        self.calls += 1
        return AdjudicationProposal(
            result_tier="success",
            key_factors=["公开 D100 已作为战争不确定性依据"],
            requested_executor_id=intent.requested_executor_id,
            actual_executor_id=self.executor_id,
            execution_status="completed",
            duration_candidate=Duration(unit="hour", value=1),
            duration_reason="短促交战",
            deltas=[
                MetricWorldDelta(
                    delta_id=DeltaId(uuid4()),
                    target_scope="world",
                    field="military_strength",
                    operation="increment",
                    before_value=state.military_strength,
                    value=10,
                ),
            ],
        )


def test_settlement_persists_executor_roll_attribution_and_exact_replay(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "world-state-settlement.db")
    saves.init_db()
    initial = create_initial_state()
    initial.ministers[0].status = MinisterStatus.ACTIVE
    initial.ministers[0].positions = initial.ministers[0].positions or ["临时行军主管"]
    root = worlds.create_game_with_root(initial)
    parent = worlds.load_version(root.version_id).state
    active_names = {
        minister.name
        for minister in parent.ministers
        if minister.status == MinisterStatus.ACTIVE
    }
    executor_id = next(
        entity_id
        for entity_id, entity in parent.entity_registry.items()
        if isinstance(entity, PersonEntity) and entity.legacy_name in active_names
    )
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text=f"命{parent.entity_registry[executor_id].display_name}出兵迎战",
        action_kind="warfare",
        requested_executor_id=executor_id,
    )
    adjudicator = _Adjudicator(executor_id)
    service = ActionService(adjudicator=adjudicator)

    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)

    facts = committed.result.facts
    assert adjudicator.calls == 1
    assert len(facts.rolls) == 1
    assert len(facts.world_state_attribution) == 1
    attribution = facts.world_state_attribution[0]
    assert attribution.roll_id == facts.rolls[0].roll_id
    assert attribution.executor_facts.actual_executor_id == executor_id
    assert facts.attribution.executor_facts == attribution.executor_facts
    assert attribution.after_value == committed.state.military_strength
    assert replayed.result.replayed is True
    assert replayed.result.facts == facts
    assert replayed.state == committed.state
    assert len(worlds.list_settlements(root.game_id, root.branch_id)) == 1
