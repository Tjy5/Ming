import pytest
from hypothesis import given, strategies as st

from engine.calendar import (
    InvalidCalendarDateError,
    UnsupportedCalendarVersionError,
    absolute_hour_from_projection,
    leap_month_for_year,
    months_in_year,
    projection_from_absolute_hour,
)


@pytest.mark.parametrize(
    ("absolute_hour", "expected"),
    [
        (0, (1328, 10, False, 29, 1, 0, "子", "秋分")),
        (23, (1328, 10, False, 29, 1, 23, "子", "秋分")),
        (24, (1328, 10, False, 29, 2, 0, "子", "秋分")),
        (696, (1328, 11, False, 30, 1, 0, "子", "霜降")),
        (2112, (1329, 1, False, 30, 1, 0, "子", "冬至")),
        (14160, (1330, 6, False, 29, 1, 0, "子", "小满")),
        (14856, (1330, 6, True, 30, 1, 0, "子", "夏至")),
        (15576, (1330, 7, False, 30, 1, 0, "子", "夏至")),
    ],
)
def test_calendar_v1_golden_vectors(absolute_hour, expected):
    projection = projection_from_absolute_hour(absolute_hour)
    assert (
        projection.year,
        projection.month,
        projection.is_leap_month,
        projection.month_length,
        projection.day,
        projection.hour,
        projection.double_hour_name,
        projection.solar_term,
    ) == expected


@pytest.mark.parametrize(
    "date",
    [
        {"year": 1328, "month": 10, "day": 1, "hour": 0},
        {"year": 1328, "month": 12, "day": 29, "hour": 23},
        {"year": 1330, "month": 6, "day": 30, "hour": 11, "is_leap_month": True},
        {"year": 1368, "month": 1, "day": 1, "hour": 0},
        {"year": 1_000_000, "month": 12, "day": 29, "hour": 22},
    ],
)
def test_projection_round_trip_is_exact(date):
    absolute_hour = absolute_hour_from_projection(**date)
    projection = projection_from_absolute_hour(absolute_hour)
    assert projection.absolute_hour == absolute_hour
    for key, value in date.items():
        assert getattr(projection, key) == value


@given(st.integers(min_value=0, max_value=10**12))
def test_absolute_hour_projection_property_round_trip(absolute_hour):
    projection = projection_from_absolute_hour(absolute_hour)
    assert absolute_hour_from_projection(
        year=projection.year,
        month=projection.month,
        day=projection.day,
        hour=projection.hour,
        is_leap_month=projection.is_leap_month,
        calendar_version=projection.calendar_version,
    ) == absolute_hour


def test_v1_leap_cycle_and_month_lengths_are_frozen():
    assert leap_month_for_year(1328) == 5
    assert leap_month_for_year(1329) is None
    assert leap_month_for_year(1330) == 6
    months = months_in_year(1330)
    assert len(months) == 13
    assert [(m.month, m.is_leap_month, m.length_days) for m in months[5:8]] == [
        (6, False, 29),
        (6, True, 30),
        (7, False, 30),
    ]


def test_solar_term_boundaries_are_deterministic():
    day_5 = projection_from_absolute_hour(
        absolute_hour_from_projection(year=1328, month=10, day=5)
    )
    day_6 = projection_from_absolute_hour(
        absolute_hour_from_projection(year=1328, month=10, day=6)
    )
    day_21 = projection_from_absolute_hour(
        absolute_hour_from_projection(year=1328, month=10, day=21)
    )
    assert day_5.solar_term == "秋分"
    assert day_6.solar_term == "寒露"
    assert day_21.solar_term == "霜降"


@pytest.mark.parametrize(
    ("hour", "expected_index", "expected_name"),
    [
        (0, 0, "子"),
        (1, 1, "丑"),
        (2, 1, "丑"),
        (3, 2, "寅"),
        (4, 2, "寅"),
        (5, 3, "卯"),
        (6, 3, "卯"),
        (7, 4, "辰"),
        (8, 4, "辰"),
        (9, 5, "巳"),
        (10, 5, "巳"),
        (11, 6, "午"),
        (12, 6, "午"),
        (13, 7, "未"),
        (14, 7, "未"),
        (15, 8, "申"),
        (16, 8, "申"),
        (17, 9, "酉"),
        (18, 9, "酉"),
        (19, 10, "戌"),
        (20, 10, "戌"),
        (21, 11, "亥"),
        (22, 11, "亥"),
        (23, 0, "子"),
    ],
)
def test_all_twenty_four_hours_project_to_the_twelve_double_hours(
    hour,
    expected_index,
    expected_name,
):
    projection = projection_from_absolute_hour(
        absolute_hour_from_projection(year=1328, month=10, day=1, hour=hour),
    )

    assert projection.double_hour_index == expected_index
    assert projection.double_hour_name == expected_name


@pytest.mark.parametrize(
    "date",
    [
        {"year": 1328, "month": 9},
        {"year": 1328, "month": 10, "day": 30},
        {"year": 1329, "month": 6, "is_leap_month": True},
        {"year": 1330, "month": 13},
        {"year": 1330, "month": 1, "hour": 24},
    ],
)
def test_invalid_calendar_dates_fail_closed(date):
    with pytest.raises(InvalidCalendarDateError):
        absolute_hour_from_projection(**date)


def test_unknown_calendar_version_never_falls_back_to_v1():
    with pytest.raises(UnsupportedCalendarVersionError):
        projection_from_absolute_hour(0, calendar_version="yuanming-calendar-v2")
