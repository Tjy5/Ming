"""Immutable data for the first Yuan-Ming world-calendar ruleset.

This is deliberately a deterministic historical approximation, not an
astronomical reconstruction.  Existing worlds persist the version string and
must keep using these exact tables when newer rulesets are added.
"""

from __future__ import annotations

from types import MappingProxyType

from models.world import DEFAULT_CALENDAR_SCHEMA_VERSION


CALENDAR_VERSION = DEFAULT_CALENDAR_SCHEMA_VERSION
EPOCH_ID = "yuanming-1328-10-01-zishi"
WORLD_TIMEZONE = "UTC+08:00"

EPOCH_YEAR = 1328
EPOCH_MONTH = 10
EPOCH_IS_LEAP_MONTH = False
EPOCH_DAY = 1
EPOCH_HOUR = 0

# Normal months alternate 30/29 days.  A leap month uses the opposite length
# of the regular month it follows, so both month sizes occur in leap slots.
REGULAR_MONTH_LENGTHS = (30, 29, 30, 29, 30, 29, 30, 29, 30, 29, 30, 29)

# Seven leap years in every 19-year cycle.  The value is the regular lunar
# month after which the leap month is inserted.  MappingProxyType prevents
# accidental runtime mutation of versioned calendar data.
LEAP_MONTH_BY_CYCLE_YEAR = MappingProxyType({
    0: 6,
    3: 5,
    6: 4,
    8: 3,
    11: 7,
    14: 6,
    17: 5,
})

DOUBLE_HOUR_NAMES = (
    "子", "丑", "寅", "卯", "辰", "巳",
    "午", "未", "申", "酉", "戌", "亥",
)

# Two deterministic solar-term boundaries per non-leap lunar month: the first
# term begins on day 6 at hour 0 and the second on day 21 at hour 0.  Leap
# months introduce no duplicate term and retain the preceding term.
SOLAR_TERMS = (
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分",
    "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
    "小暑", "大暑", "立秋", "处暑", "白露", "秋分",
    "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
)

ERA_TABLE = (
    (1328, "天历"),
    (1330, "至顺"),
    (1333, "元统"),
    (1335, "至元"),
    (1341, "至正"),
    (1368, "洪武"),
)
