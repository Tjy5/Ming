from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from api.action_service import ActionService
from db import saves, worlds
from engine.calendar import ensure_game_time_clock, normalize_duration
from engine.settlement import SettlementValidationError, apply_world_deltas
from engine.world_state import WorldStateValidationError, metric_projection
from models.game import create_initial_state
from models.settlement import ActionIntent, AdjudicationProposal, ModifierWorldDelta
from models.world import DeltaId, Duration, WorldInstant, new_client_action_id
from models.world_state import MetricTarget, ModifierRecord, ModifierTransform


def _record(state, modifier_id="plague", *, stacking_policy="stack") -> ModifierRecord:
    start = ensure_game_time_clock(state.time)
    end = normalize_duration(start, Duration(unit="month", value=1)).end
    return ModifierRecord(
        modifier_id=modifier_id,
        name="疫病压力",
        target=MetricTarget(target_scope="world", metric_key="civil_morale"),
        source_kind="event",
        source_ref="event:plague",
        transform=ModifierTransform(kind="add", amount=Decimal("-20")),
        started_at=start,
        ends_at=end,
        stacking_group="plague",
        stacking_policy=stacking_policy,
    )


def _create_delta(record: ModifierRecord) -> ModifierWorldDelta:
    return ModifierWorldDelta(
        delta_id=DeltaId(uuid4()),
        operation="create",
        modifier_id=record.modifier_id,
        record=record,
    )


def test_modifier_keeps_base_and_effective_values_separate():
    state = create_initial_state()
    state.civil_morale = 60
    changed = apply_world_deltas(state, [_create_delta(_record(state))])
    projection = metric_projection(changed, "civil_morale")

    assert changed.civil_morale == 60
    assert projection.base_value == 60
    assert projection.effective_value == 40
    assert projection.base_band == "平稳"
    assert projection.effective_band == "不稳"


def test_exclusive_modifier_conflict_rejects_the_whole_application():
    state = create_initial_state()
    first = _record(state, "one", stacking_policy="exclusive")
    second = _record(state, "two", stacking_policy="exclusive")
    changed = apply_world_deltas(state, [_create_delta(first)])

    with pytest.raises(SettlementValidationError) as exc:
        apply_world_deltas(changed, [_create_delta(second)])
    assert exc.value.code == "modifier_conflict"
    assert "two" not in changed.world_state.modifiers


def test_timed_modifier_projection_requires_a_canonical_clock():
    state = create_initial_state()
    record = _record(state)
    state.world_state.modifiers[record.modifier_id] = record
    state.time.clock = None

    with pytest.raises(WorldStateValidationError) as exc:
        metric_projection(state, "civil_morale")
    assert exc.value.code == "invalid_time_contract"


def test_modifier_cannot_be_ended_twice_or_rewrite_its_end_time():
    state = create_initial_state()
    created = apply_world_deltas(state, [_create_delta(_record(state))])
    first_end = WorldInstant.model_validate(created.time.clock.model_dump())
    ended = apply_world_deltas(
        created,
        [
            ModifierWorldDelta(
                delta_id=DeltaId(uuid4()),
                operation="end",
                modifier_id="plague",
                ended_at=first_end,
            ),
        ],
    )
    second_end = first_end.model_copy(
        update={"absolute_hour": first_end.absolute_hour + 1},
    )

    with pytest.raises(SettlementValidationError) as exc:
        apply_world_deltas(
            ended,
            [
                ModifierWorldDelta(
                    delta_id=DeltaId(uuid4()),
                    operation="end",
                    modifier_id="plague",
                    ended_at=second_end,
                ),
            ],
        )
    assert exc.value.code == "delta_precondition_failed"
    assert ended.world_state.modifiers["plague"].ended_at == first_end


def test_modifier_end_rejects_a_different_clock_identity():
    state = create_initial_state()
    created = apply_world_deltas(state, [_create_delta(_record(state))])
    wrong_clock = WorldInstant.model_validate(created.time.clock.model_dump()).model_copy(
        update={"epoch_id": "different-epoch"},
    )

    with pytest.raises(SettlementValidationError) as exc:
        apply_world_deltas(
            created,
            [
                ModifierWorldDelta(
                    delta_id=DeltaId(uuid4()),
                    operation="end",
                    modifier_id="plague",
                    before_status="active",
                    ended_at=wrong_clock,
                ),
            ],
        )
    assert exc.value.code == "invalid_time_contract"


class _MonthAdjudicator:
    async def adjudicate(self, _intent, _state):
        return AdjudicationProposal(
            result_tier="success",
            execution_status="completed",
            duration_candidate=Duration(unit="month", value=1),
            duration_reason="等待修正到期",
        )


def test_modifier_expiry_is_a_typed_elapsed_delta_and_replays(monkeypatch, tmp_path):
    monkeypatch.setattr(saves, "DB_PATH", tmp_path / "modifier.db")
    saves.init_db()
    state = create_initial_state()
    state.world_state.modifiers["plague"] = _record(state)
    root = worlds.create_game_with_root(state)
    intent = ActionIntent(
        game_id=root.game_id,
        branch_id=root.branch_id,
        expected_parent_version_id=root.version_id,
        client_action_id=new_client_action_id(),
        raw_text="等待一月",
        action_kind="wait",
    )
    service = ActionService(adjudicator=_MonthAdjudicator())

    committed = service.execute_sync(intent)
    replayed = service.execute_sync(intent)

    assert committed.state.world_state.modifiers["plague"].status == "ended"
    expiry = [
        delta
        for delta in committed.result.facts.deltas
        if isinstance(delta, ModifierWorldDelta)
    ]
    assert len(expiry) == 1
    assert isinstance(expiry[0].ended_at, WorldInstant)
    assert replayed.result.replayed is True
    assert replayed.state == committed.state
