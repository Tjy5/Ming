import math

import pytest
from pydantic import ValidationError

from engine.calendar import (
    absolute_hour_from_projection,
    instant_from_absolute_hour,
    normalize_duration,
)
from models.world import Duration


@pytest.mark.parametrize(
    "payload",
    [
        {"unit": "hour", "value": 0},
        {"unit": "day", "value": -1},
        {"unit": "month", "value": 1.5},
        {"unit": "year", "value": True},
        {"unit": "week", "value": 1},
        {"unit": "hour", "value": math.inf},
    ],
)
def test_invalid_duration_is_rejected_by_the_typed_boundary(payload):
    with pytest.raises(ValidationError):
        Duration.model_validate(payload)


@pytest.mark.parametrize("unit", ["hour", "day", "month", "year"])
def test_positive_integer_duration_round_trips(unit):
    duration = Duration(unit=unit, value=2)
    assert Duration.model_validate(duration.model_dump(mode="json")) == duration


def test_hour_and_day_are_absolute_elapsed_time():
    start = instant_from_absolute_hour(100)
    hour_result = normalize_duration(start, Duration(unit="hour", value=5))
    day_result = normalize_duration(start, Duration(unit="day", value=2))
    assert hour_result.end.absolute_hour == 105
    assert hour_result.elapsed_hours == 5
    assert day_result.end.absolute_hour == 148
    assert day_result.elapsed_hours == 48


def test_month_duration_clamps_missing_day_to_target_month_end():
    start_hour = absolute_hour_from_projection(
        year=1329,
        month=1,
        day=30,
        hour=5,
    )
    result = normalize_duration(
        instant_from_absolute_hour(start_hour),
        Duration(unit="month", value=1),
    )
    assert (
        result.end_calendar.year,
        result.end_calendar.month,
        result.end_calendar.day,
        result.end_calendar.hour,
    ) == (1329, 2, 29, 5)


def test_month_duration_enters_and_exits_leap_month_in_sequence():
    start_hour = absolute_hour_from_projection(year=1330, month=6, day=29)
    one_month = normalize_duration(
        instant_from_absolute_hour(start_hour),
        Duration(unit="month", value=1),
    )
    two_months = normalize_duration(
        instant_from_absolute_hour(start_hour),
        Duration(unit="month", value=2),
    )
    assert (
        one_month.end_calendar.month,
        one_month.end_calendar.is_leap_month,
        one_month.end_calendar.day,
    ) == (6, True, 29)
    assert (
        two_months.end_calendar.month,
        two_months.end_calendar.is_leap_month,
        two_months.end_calendar.day,
    ) == (7, False, 29)


def test_year_duration_maps_missing_leap_month_to_regular_month_and_clamps():
    start_hour = absolute_hour_from_projection(
        year=1330,
        month=6,
        is_leap_month=True,
        day=30,
        hour=7,
    )
    result = normalize_duration(
        instant_from_absolute_hour(start_hour),
        Duration(unit="year", value=1),
    )
    assert (
        result.end_calendar.year,
        result.end_calendar.month,
        result.end_calendar.is_leap_month,
        result.end_calendar.day,
        result.end_calendar.hour,
    ) == (1331, 6, False, 29, 7)


def test_large_month_duration_uses_the_frozen_19_year_cycle():
    start_hour = absolute_hour_from_projection(year=1329, month=1)
    result = normalize_duration(
        instant_from_absolute_hour(start_hour),
        Duration(unit="month", value=235),
    )
    assert (
        result.end_calendar.year,
        result.end_calendar.month,
        result.end_calendar.is_leap_month,
    ) == (1348, 1, False)
