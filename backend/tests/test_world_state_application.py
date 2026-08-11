from __future__ import annotations

from uuid import uuid4

import pytest

from engine.execution import build_executor_facts
from engine.settlement import apply_world_deltas_with_facts
from models.enums import MinisterStatus
from models.game import GameState, Minister, MinisterAbilities
from models.settlement import MetricWorldDelta
from models.world import DeltaId, EntitySource, PersonEntity, RegionEntity, new_entity_id


def _state_with_executor(name: str, *, civil: int, loyalty: int, corruption: int):
    state = GameState(
        national_treasury=100,
        ministers=[
            Minister(
                name=name,
                faction="test",
                abilities=MinisterAbilities(civil=civil),
                loyalty=loyalty,
                corruption=corruption,
                status=MinisterStatus.ACTIVE,
                positions=["中书省左丞相"],
            ),
        ],
    )
    entity_id = new_entity_id()
    state.entity_registry[entity_id] = PersonEntity(
        entity_id=entity_id,
        display_name=name,
        legacy_name=name,
        source=EntitySource(kind="system", reference="test"),
    )
    return state, entity_id


def _treasury_delta(before: int = 100, value: int = 100) -> MetricWorldDelta:
    return MetricWorldDelta(
        delta_id=DeltaId(uuid4()),
        target_scope="world",
        field="national_treasury",
        operation="increment",
        before_value=before,
        value=value,
    )


def test_metric_application_has_no_executor_average_or_hidden_minimum_deviation():
    state, _ = _state_with_executor("甲", civil=0, loyalty=0, corruption=100)
    state.execution_rng_seed = 12345
    changed, facts = apply_world_deltas_with_facts(state, [_treasury_delta()])

    assert changed.national_treasury == 200
    assert facts[0].executor_facts is None
    assert facts[0].executor_adjustment == 0
    assert facts[0].actual_delta == 100


def test_only_actual_executor_changes_the_deterministic_result():
    high, high_id = _state_with_executor("能臣", civil=100, loyalty=100, corruption=0)
    low, low_id = _state_with_executor("庸臣", civil=0, loyalty=5, corruption=95)
    high_facts = build_executor_facts(
        high,
        requested_executor_id=high_id,
        actual_executor_id=high_id,
        execution_status="completed",
        action_kind="governance",
    )
    low_facts = build_executor_facts(
        low,
        requested_executor_id=low_id,
        actual_executor_id=low_id,
        execution_status="completed",
        action_kind="governance",
    )

    high_result, high_attr = apply_world_deltas_with_facts(
        high,
        [_treasury_delta()],
        executor_facts=high_facts,
    )
    low_result, low_attr = apply_world_deltas_with_facts(
        low,
        [_treasury_delta()],
        executor_facts=low_facts,
    )

    assert high_result.national_treasury > low_result.national_treasury
    assert high_attr[0].executor_facts.actual_executor_id == high_id
    assert low_attr[0].executor_facts.actual_executor_id == low_id
    assert high_attr[0].after_value == high_result.national_treasury
    assert low_attr[0].after_value == low_result.national_treasury


def test_metric_precision_and_clamp_are_recorded_once():
    state = GameState(civil_morale=99)
    delta = MetricWorldDelta(
        delta_id=DeltaId(uuid4()),
        target_scope="world",
        field="civil_morale",
        operation="increment",
        before_value=99,
        value=10,
    )
    changed, facts = apply_world_deltas_with_facts(state, [delta])

    assert changed.civil_morale == 100
    assert facts[0].actual_delta == 1
    assert facts[0].clamp_adjustment == -9


def test_region_entity_cannot_be_used_as_an_executor():
    state = GameState()
    region_id = new_entity_id()
    state.entity_registry[region_id] = RegionEntity(
        entity_id=region_id,
        display_name="测试地区",
        source=EntitySource(kind="system", reference="test"),
    )

    with pytest.raises(ValueError, match="actual executor must be"):
        build_executor_facts(
            state,
            requested_executor_id=region_id,
            actual_executor_id=region_id,
            execution_status="attempted",
        )
