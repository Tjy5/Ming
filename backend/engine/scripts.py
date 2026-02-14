from __future__ import annotations

from dataclasses import dataclass, field

from models.game import StructuredDecree
from models.enums import DecreeType, PersonnelAction


@dataclass
class ScriptChoice:
    label: str
    description: str
    decrees: list[StructuredDecree] = field(default_factory=list)


@dataclass
class ScriptEvent:
    script_id: str
    trigger_year: int
    trigger_month: int
    title: str
    rich_description: str
    choices: list[ScriptChoice]
    is_blocking: bool = False


# ── Script Registry ─────────────────────────────────────

SCRIPT_REGISTRY: dict[str, ScriptEvent] = {}


def _register(evt: ScriptEvent) -> None:
    if not evt.script_id:
        raise ValueError("script_id must be non-empty")
    if evt.script_id in SCRIPT_REGISTRY:
        raise ValueError(f"duplicate script_id: {evt.script_id}")
    if not 1621 <= evt.trigger_year <= 1644:
        raise ValueError(f"trigger_year out of range: {evt.trigger_year}")
    if not 1 <= evt.trigger_month <= 12:
        raise ValueError(f"trigger_month out of range: {evt.trigger_month}")
    if not evt.choices:
        raise ValueError(f"script {evt.script_id} must have at least one choice")
    SCRIPT_REGISTRY[evt.script_id] = evt


def get_scripts_for_time(year: int, month: int) -> list[ScriptEvent]:
    return [
        e for e in SCRIPT_REGISTRY.values()
        if e.trigger_year == year and e.trigger_month == month
    ]


# ── Scripts ─────────────────────────────────────────────

_register(ScriptEvent(
    script_id="tianqi-7-opening",
    trigger_year=1627,
    trigger_month=1,
    title="天启七年·天下大势",
    is_blocking=True,
    rich_description=(
        "**天启七年，正月。**\n\n"
        "紫禁城上空阴云密布。先帝驾崩未久，新君即位，百废待兴。\n\n"
        "**朝局：** 魏忠贤余党盘踞朝堂，东林党人蠢蠢欲动，"
        "朝中派系倾轧已至白热化。\n\n"
        "**边患：** 辽东后金虎视眈眈，宁远虽胜犹危，"
        "边军粮饷拖欠日久，军心浮动。\n\n"
        "**民变：** 陕西连年大旱，赤地千里，饥民遍野，"
        "流寇之势已成燎原。\n\n"
        "**财政：** 国库空虚，入不敷出。加征辽饷已令百姓苦不堪言，"
        "然边防军需仍捉襟见肘。\n\n"
        "天下大势，危如累卵。新君当何以自处？"
    ),
    choices=[
        ScriptChoice(
            label="清除阉党，整顿朝纲",
            description="立即着手清除魏忠贤余党，重用东林贤臣，以正朝纲。此举可提振朝廷威望，但可能引发阉党残余的激烈反扑。",
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="魏忠贤",
                sub_action=PersonnelAction.DISMISS,
            )],
        ),
        ScriptChoice(
            label="暂观时局，徐图后计",
            description="初登大宝，根基未稳。先稳住各方势力，摸清朝局虚实，再做定夺。",
            decrees=[],
        ),
    ],
))
