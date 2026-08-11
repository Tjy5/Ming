from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.calendar import absolute_hour_from_projection, instant_from_absolute_hour
from engine.clock import (
    ClockConsumerRegistry,
    ClockPlanningError,
    plan_elapsed_segment,
)
from models.game import create_initial_state
from models.world import Duration, ElapsedSegmentPlan, new_client_action_id


def _instant(*, year: int, month: int, day: int, hour: int = 0):
    return instant_from_absolute_hour(
        absolute_hour_from_projection(
            year=year,
            month=month,
            day=day,
            hour=hour,
        ),
    )


def test_boundaries_use_open_start_closed_end_and_keep_same_hour_facts():
    action_id = new_client_action_id()
    start = _instant(year=1328, month=10, day=5, hour=23)

    first = plan_elapsed_segment(
        source_action_id=action_id,
        start=start,
        duration=Duration(unit="hour", value=1),
    )
    repeated = plan_elapsed_segment(
        source_action_id=action_id,
        start=start,
        duration=Duration(unit="hour", value=1),
    )

    assert [boundary.kind for boundary in first.boundaries] == [
        "day",
        "solar_term",
        "end",
    ]
    assert {boundary.absolute_hour for boundary in first.boundaries} == {
        start.absolute_hour + 1,
    }
    assert first.boundaries[1].projection.solar_term == "寒露"
    assert all(
        boundary.epoch_id == first.segment.start.epoch_id
        and boundary.world_timezone == first.segment.start.world_timezone
        for boundary in first.boundaries
    )
    assert len({boundary.boundary_id for boundary in first.boundaries}) == 3
    assert repeated == first


def test_year_boundary_order_is_deterministic_and_not_deduplicated_by_hour():
    start = _instant(year=1328, month=12, day=29, hour=23)

    plan = plan_elapsed_segment(
        source_action_id=new_client_action_id(),
        start=start,
        duration=Duration(unit="hour", value=1),
    )

    assert [boundary.kind for boundary in plan.boundaries] == [
        "day",
        "month",
        "year",
        "end",
    ]
    assert plan.normalized_duration.end_calendar.year == 1329
    assert plan.normalized_duration.end_calendar.month == 1
    assert plan.normalized_duration.end_calendar.day == 1


def test_boundary_limit_requires_future_activity_contract():
    with pytest.raises(ClockPlanningError) as exc_info:
        plan_elapsed_segment(
            source_action_id=new_client_action_id(),
            start=_instant(year=1328, month=10, day=1),
            duration=Duration(unit="year", value=2),
            max_boundaries=32,
        )

    assert exc_info.value.code == "activity_contract_required"


def test_registry_orders_invocations_and_dispatches_the_persisted_sequence():
    calls: list[str] = []

    class _Consumer:
        version = "v1"
        boundary_kinds = frozenset({"end"})

        def __init__(self, name: str, order: int):
            self.name = name
            self.order = order

        def consume(self, **kwargs):
            calls.append(kwargs["invocation"].consumer_name)
            return []

    registry = ClockConsumerRegistry(
        [
            _Consumer("slow", 20),
            _Consumer("beta", 10),
            _Consumer("alpha", 10),
        ],
    )
    plan = plan_elapsed_segment(
        source_action_id=new_client_action_id(),
        start=_instant(year=1328, month=10, day=1),
        duration=Duration(unit="hour", value=1),
        registry=registry,
    )

    assert [
        invocation.consumer_name for invocation in plan.consumer_invocations
    ] == ["alpha", "beta", "slow"]
    assert [invocation.ordinal for invocation in plan.consumer_invocations] == [0, 1, 2]
    assert registry.dispatch(create_initial_state(), plan) == ()
    assert calls == ["alpha", "beta", "slow"]

    payload = plan.model_dump(mode="json")
    payload["consumer_invocations"][0]["boundary_kind"] = "day"
    with pytest.raises(ValidationError, match="boundary kind mismatch"):
        ElapsedSegmentPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    payload["consumer_invocations"][1]["ordinal"] = 0
    with pytest.raises(ValidationError, match="ordinals must be contiguous"):
        ElapsedSegmentPlan.model_validate(payload)

    registry.consumers[0].boundary_kinds = frozenset({"day"})
    with pytest.raises(ClockPlanningError) as exc_info:
        registry.dispatch(create_initial_state(), plan)
    assert exc_info.value.code == "clock_consumer_registry_mismatch"

    with pytest.raises(ClockPlanningError) as exc_info:
        registry.register(_Consumer("alpha", 99))
    assert exc_info.value.code == "duplicate_clock_consumer"
