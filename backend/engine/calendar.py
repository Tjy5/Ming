"""Versioned absolute world clock and deterministic lunar-calendar projection."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from models.world import (
    CalendarProjection,
    Duration,
    NormalizedDuration,
    WorldClock,
    WorldInstant,
)

from . import calendar_v1

if TYPE_CHECKING:
    from models.game import GameTime


class CalendarError(ValueError):
    """Base error for deterministic calendar validation failures."""


class UnsupportedCalendarVersionError(CalendarError):
    pass


class InvalidCalendarDateError(CalendarError):
    pass


@dataclass(frozen=True, slots=True)
class CalendarMonth:
    year: int
    month: int
    is_leap_month: bool
    length_days: int


_CALENDAR_CYCLE_YEARS = 38
_MONTH_CYCLE_YEARS = 19
_MONTHS_PER_19_YEARS = 19 * 12 + len(calendar_v1.LEAP_MONTH_BY_CYCLE_YEAR)


def _require_v1(calendar_version: str) -> None:
    if calendar_version != calendar_v1.CALENDAR_VERSION:
        raise UnsupportedCalendarVersionError(
            f"unsupported calendar version: {calendar_version}"
        )


def resolve_era(year: int) -> tuple[str, int]:
    start_year, era_name = calendar_v1.ERA_TABLE[0]
    for candidate_year, candidate_name in calendar_v1.ERA_TABLE:
        if candidate_year > year:
            break
        start_year, era_name = candidate_year, candidate_name
    return era_name, year - start_year + 1


def leap_month_for_year(year: int) -> int | None:
    return calendar_v1.LEAP_MONTH_BY_CYCLE_YEAR.get(year % _MONTH_CYCLE_YEARS)


@lru_cache(maxsize=None)
def months_in_year(year: int) -> tuple[CalendarMonth, ...]:
    leap_month = leap_month_for_year(year)
    result: list[CalendarMonth] = []
    for month, regular_length in enumerate(calendar_v1.REGULAR_MONTH_LENGTHS, start=1):
        result.append(CalendarMonth(year, month, False, regular_length))
        if leap_month == month:
            result.append(CalendarMonth(year, month, True, 59 - regular_length))
    return tuple(result)


@lru_cache(maxsize=None)
def _year_length_days(year: int) -> int:
    return sum(month.length_days for month in months_in_year(year))


def _epoch_tail_months() -> tuple[CalendarMonth, ...]:
    return tuple(
        month
        for month in months_in_year(calendar_v1.EPOCH_YEAR)
        if (month.month, month.is_leap_month)
        >= (calendar_v1.EPOCH_MONTH, calendar_v1.EPOCH_IS_LEAP_MONTH)
    )


_EPOCH_TAIL_MONTHS = _epoch_tail_months()
_EPOCH_TAIL_DAYS = sum(month.length_days for month in _EPOCH_TAIL_MONTHS)
_CYCLE_START_YEAR = calendar_v1.EPOCH_YEAR + 1
_CALENDAR_CYCLE_DAYS = sum(
    _year_length_days(_CYCLE_START_YEAR + offset)
    for offset in range(_CALENDAR_CYCLE_YEARS)
)


def _days_from_epoch_to_year_start(year: int) -> int:
    if year <= calendar_v1.EPOCH_YEAR:
        if year == calendar_v1.EPOCH_YEAR:
            return 0
        raise InvalidCalendarDateError("world instants cannot precede the calendar epoch")
    full_years = year - _CYCLE_START_YEAR
    cycles, remainder = divmod(full_years, _CALENDAR_CYCLE_YEARS)
    return (
        _EPOCH_TAIL_DAYS
        + cycles * _CALENDAR_CYCLE_DAYS
        + sum(_year_length_days(_CYCLE_START_YEAR + offset) for offset in range(remainder))
    )


def _month_position(
    year: int,
    month: int,
    is_leap_month: bool,
) -> tuple[tuple[CalendarMonth, ...], int]:
    months = months_in_year(year)
    for index, candidate in enumerate(months):
        if (candidate.month, candidate.is_leap_month) == (month, is_leap_month):
            return months, index
    qualifier = "leap " if is_leap_month else ""
    raise InvalidCalendarDateError(f"{year} has no {qualifier}month {month}")


def absolute_hour_from_projection(
    *,
    year: int,
    month: int,
    day: int = 1,
    hour: int = 0,
    is_leap_month: bool = False,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
) -> int:
    _require_v1(calendar_version)
    if isinstance(year, bool) or not isinstance(year, int):
        raise InvalidCalendarDateError("year must be an integer")
    if isinstance(month, bool) or not isinstance(month, int):
        raise InvalidCalendarDateError("month must be an integer")
    if isinstance(day, bool) or not isinstance(day, int):
        raise InvalidCalendarDateError("day must be an integer")
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise InvalidCalendarDateError("hour must be an integer in [0, 23]")

    months, target_index = _month_position(year, month, is_leap_month)
    target = months[target_index]
    if not 1 <= day <= target.length_days:
        raise InvalidCalendarDateError(
            f"day must be in [1, {target.length_days}] for the target month"
        )

    if year == calendar_v1.EPOCH_YEAR:
        epoch_index = next(
            index
            for index, candidate in enumerate(months)
            if (candidate.month, candidate.is_leap_month)
            == (calendar_v1.EPOCH_MONTH, calendar_v1.EPOCH_IS_LEAP_MONTH)
        )
        if target_index < epoch_index:
            raise InvalidCalendarDateError("world instants cannot precede the calendar epoch")
        days = sum(candidate.length_days for candidate in months[epoch_index:target_index])
    else:
        days = _days_from_epoch_to_year_start(year)
        days += sum(candidate.length_days for candidate in months[:target_index])
    days += day - 1
    return days * 24 + hour


def _locate_month(
    months: tuple[CalendarMonth, ...],
    remaining_days: int,
) -> tuple[CalendarMonth, int]:
    for candidate in months:
        if remaining_days < candidate.length_days:
            return candidate, remaining_days
        remaining_days -= candidate.length_days
    raise AssertionError("calendar month lookup exceeded the selected year")


def _solar_term(month: int, day: int, is_leap_month: bool) -> str:
    if is_leap_month:
        return calendar_v1.SOLAR_TERMS[month * 2 - 1]
    if day >= 21:
        return calendar_v1.SOLAR_TERMS[month * 2 - 1]
    if day >= 6:
        return calendar_v1.SOLAR_TERMS[(month - 1) * 2]
    return calendar_v1.SOLAR_TERMS[((month - 2) * 2 + 1) % 24]


def projection_from_absolute_hour(
    absolute_hour: int,
    *,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
) -> CalendarProjection:
    _require_v1(calendar_version)
    if isinstance(absolute_hour, bool) or not isinstance(absolute_hour, int):
        raise InvalidCalendarDateError("absolute_hour must be an integer")
    if absolute_hour < 0:
        raise InvalidCalendarDateError("absolute_hour cannot precede the epoch")

    remaining_days, hour = divmod(absolute_hour, 24)
    if remaining_days < _EPOCH_TAIL_DAYS:
        month_info, day_offset = _locate_month(_EPOCH_TAIL_MONTHS, remaining_days)
    else:
        remaining_days -= _EPOCH_TAIL_DAYS
        cycles, remaining_days = divmod(remaining_days, _CALENDAR_CYCLE_DAYS)
        year = _CYCLE_START_YEAR + cycles * _CALENDAR_CYCLE_YEARS
        while remaining_days >= _year_length_days(year):
            remaining_days -= _year_length_days(year)
            year += 1
        month_info, day_offset = _locate_month(months_in_year(year), remaining_days)

    day = day_offset + 1
    double_hour_index = ((hour + 1) // 2) % 12
    era_name, era_year = resolve_era(month_info.year)
    return CalendarProjection(
        absolute_hour=absolute_hour,
        calendar_version=calendar_version,
        year=month_info.year,
        month=month_info.month,
        is_leap_month=month_info.is_leap_month,
        month_length=month_info.length_days,
        day=day,
        hour=hour,
        double_hour_index=double_hour_index,
        double_hour_name=calendar_v1.DOUBLE_HOUR_NAMES[double_hour_index],
        solar_term=_solar_term(month_info.month, day, month_info.is_leap_month),
        era_name=era_name,
        era_year=era_year,
    )


def instant_from_absolute_hour(
    absolute_hour: int,
    *,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
) -> WorldInstant:
    _require_v1(calendar_version)
    return WorldInstant(
        absolute_hour=absolute_hour,
        calendar_version=calendar_version,
        epoch_id=calendar_v1.EPOCH_ID,
        world_timezone=calendar_v1.WORLD_TIMEZONE,
    )


def clock_from_absolute_hour(
    absolute_hour: int,
    *,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
) -> WorldClock:
    instant = instant_from_absolute_hour(
        absolute_hour,
        calendar_version=calendar_version,
    )
    return WorldClock(**instant.model_dump())


def clock_and_projection_from_calendar(
    *,
    year: int,
    month: int,
    day: int = 1,
    hour: int = 0,
    is_leap_month: bool = False,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
) -> tuple[WorldClock, CalendarProjection]:
    absolute_hour = absolute_hour_from_projection(
        year=year,
        month=month,
        day=day,
        hour=hour,
        is_leap_month=is_leap_month,
        calendar_version=calendar_version,
    )
    return (
        clock_from_absolute_hour(absolute_hour, calendar_version=calendar_version),
        projection_from_absolute_hour(absolute_hour, calendar_version=calendar_version),
    )


def _shift_month(
    year: int,
    month: int,
    is_leap_month: bool,
    count: int,
) -> CalendarMonth:
    months, index = _month_position(year, month, is_leap_month)
    if count == 0:
        return months[index]

    remaining_in_year = len(months) - index - 1
    if count <= remaining_in_year:
        return months[index + count]
    count -= remaining_in_year + 1
    year += 1
    if count == 0:
        return months_in_year(year)[0]

    cycles, count = divmod(count, _MONTHS_PER_19_YEARS)
    year += cycles * _MONTH_CYCLE_YEARS
    while True:
        months = months_in_year(year)
        if count < len(months):
            return months[count]
        count -= len(months)
        year += 1


def normalize_duration(
    start: WorldInstant,
    duration: Duration,
) -> NormalizedDuration:
    _require_v1(start.calendar_version)
    start_projection = projection_from_absolute_hour(
        start.absolute_hour,
        calendar_version=start.calendar_version,
    )

    if duration.unit == "hour":
        end_absolute_hour = start.absolute_hour + duration.value
    elif duration.unit == "day":
        end_absolute_hour = start.absolute_hour + duration.value * 24
    elif duration.unit == "month":
        target_month = _shift_month(
            start_projection.year,
            start_projection.month,
            start_projection.is_leap_month,
            duration.value,
        )
        target_day = min(start_projection.day, target_month.length_days)
        end_absolute_hour = absolute_hour_from_projection(
            year=target_month.year,
            month=target_month.month,
            day=target_day,
            hour=start_projection.hour,
            is_leap_month=target_month.is_leap_month,
            calendar_version=start.calendar_version,
        )
    else:
        target_year = start_projection.year + duration.value
        preserve_leap = (
            start_projection.is_leap_month
            and leap_month_for_year(target_year) == start_projection.month
        )
        target_months, target_index = _month_position(
            target_year,
            start_projection.month,
            preserve_leap,
        )
        target_month = target_months[target_index]
        target_day = min(start_projection.day, target_month.length_days)
        end_absolute_hour = absolute_hour_from_projection(
            year=target_year,
            month=target_month.month,
            day=target_day,
            hour=start_projection.hour,
            is_leap_month=target_month.is_leap_month,
            calendar_version=start.calendar_version,
        )

    end = instant_from_absolute_hour(
        end_absolute_hour,
        calendar_version=start.calendar_version,
    )
    return NormalizedDuration(
        duration=duration,
        start=start,
        end=end,
        elapsed_hours=end.absolute_hour - start.absolute_hour,
        start_calendar=start_projection,
        end_calendar=projection_from_absolute_hour(
            end.absolute_hour,
            calendar_version=start.calendar_version,
        ),
    )


def set_game_time_projection(
    game_time: GameTime,
    *,
    year: int,
    month: int,
    day: int = 1,
    hour: int = 0,
    is_leap_month: bool = False,
    calendar_version: str = calendar_v1.CALENDAR_VERSION,
    migration_source: str | None = None,
) -> None:
    clock, projection = clock_and_projection_from_calendar(
        year=year,
        month=month,
        day=day,
        hour=hour,
        is_leap_month=is_leap_month,
        calendar_version=calendar_version,
    )
    game_time.clock = clock
    game_time.calendar = projection
    game_time.year = projection.year
    game_time.month = projection.month
    game_time.era_name = projection.era_name
    game_time.era_year = projection.era_year
    if migration_source is not None:
        game_time.time_migration_source = migration_source


def ensure_game_time_clock(game_time: GameTime) -> WorldInstant:
    clock = game_time.clock
    calendar = game_time.calendar
    compatible = (
        clock is not None
        and calendar is not None
        and clock.absolute_hour == calendar.absolute_hour
        and clock.calendar_version == calendar.calendar_version
        and (game_time.year, game_time.month) == (calendar.year, calendar.month)
    )
    if not compatible:
        set_game_time_projection(
            game_time,
            year=game_time.year,
            month=game_time.month,
            migration_source=game_time.time_migration_source or "legacy_year_month",
        )
        clock = game_time.clock
    assert clock is not None
    return instant_from_absolute_hour(
        clock.absolute_hour,
        calendar_version=clock.calendar_version,
    )


def advance_game_time(game_time: GameTime, duration: Duration) -> NormalizedDuration:
    normalized = normalize_duration(ensure_game_time_clock(game_time), duration)
    end_projection = normalized.end_calendar
    set_game_time_projection(
        game_time,
        year=end_projection.year,
        month=end_projection.month,
        day=end_projection.day,
        hour=end_projection.hour,
        is_leap_month=end_projection.is_leap_month,
        calendar_version=end_projection.calendar_version,
        migration_source=game_time.time_migration_source,
    )
    return normalized
