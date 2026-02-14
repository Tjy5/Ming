from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from models.game import GameState

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
    condition: Callable[[GameState], bool] | None = None


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
    trigger_month=10,
    title="天启七年·朝局抉择",
    is_blocking=True,
    rich_description=(
        "**天启七年，十月。**\n\n"
        "紫禁城上空阴云密布。先帝驾崩未久，新君即位，百废待兴。\n\n"
        "**朝局：** 魏忠贤及其阉党盘踞朝堂二十余年，卖官鬻爵、排斥异己，"
        "朝中正直之士莫不切齿。东林党人蠢蠢欲动，上疏弹劾之声日盛。\n\n"
        "**边患：** 辽东后金虎视眈眈，宁远虽胜犹危，"
        "边军粮饷拖欠日久，军心浮动。\n\n"
        "**民变：** 陕西连年大旱，赤地千里，饥民遍野，"
        "流寇之势已成燎原。\n\n"
        "**财政：** 国库空虚，入不敷出。加征辽饷已令百姓苦不堪言，"
        "然边防军需仍捉襟见肘。\n\n"
        "天下大势，危如累卵。眼下最紧迫之事——魏忠贤，当如何处置？"
    ),
    choices=[
        ScriptChoice(
            label="清算阉党，整顿朝纲",
            description=(
                "雷厉风行，将魏忠贤一党连根拔除，重用东林贤臣以正朝纲。"
                "此举可大振朝廷威望，但阉党残余恐狗急跳墙。"
            ),
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="魏忠贤",
                sub_action=PersonnelAction.DISMISS,
            )],
        ),
        ScriptChoice(
            label="暂缓处置，稳住局面",
            description=(
                "初登大宝，根基未稳。暂且按兵不动，徐图后计。"
                "然东林党人恐对新君大失所望。"
            ),
            decrees=[],
        ),
        ScriptChoice(
            label="部分清算，徐图后计",
            description=(
                "去其首恶，留其羽翼，分化瓦解阉党势力。"
                "虽不如雷霆手段痛快，却可减少反弹风险。"
            ),
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="魏忠贤",
                sub_action=PersonnelAction.DISMISS,
                parameters={"partial_purge": True},
            )],
        ),
    ],
))


def _faction_field(state, faction_name: str, field: str) -> int | None:
    f = next((f for f in state.factions if f.name == faction_name), None)
    return getattr(f, field) if f else None


_register(ScriptEvent(
    script_id="eunuch-backlash",
    trigger_year=1627,
    trigger_month=12,
    title="阉党残余反扑",
    is_blocking=False,
    condition=lambda s: (_v := _faction_field(s, "阉党残余", "rebellion_risk")) is not None and _v > 40,
    rich_description=(
        "**天启七年，腊月。**\n\n"
        "锦衣卫密报：各地阉党余孽暗中串联，散布谣言，煽动军民。"
        "京师坊间流言四起，人心惶惶。有司奏报，数名被罢黜的阉党官员"
        "暗中联络边镇将领，图谋不轨。\n\n"
        "阉党虽失首脑，余焰犹存。当如何应对？"
    ),
    choices=[
        ScriptChoice(
            label="严厉镇压",
            description="调动锦衣卫彻查阉党余孽，严惩不贷。虽耗费资源，但可进一步削弱阉党根基。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
        ),
        ScriptChoice(
            label="安抚怀柔",
            description="发布诏书安抚人心，既往不咎，争取阉党余众归附。此举可缓和局势，但恐难根除隐患。",
            decrees=[],
        ),
    ],
))

_register(ScriptEvent(
    script_id="donglin-impeachment",
    trigger_year=1628,
    trigger_month=1,
    title="东林党上疏弹劾",
    is_blocking=False,
    condition=lambda s: (_v := _faction_field(s, "东林党", "satisfaction")) is not None and _v < 60,
    rich_description=(
        "**崇祯元年，正月。**\n\n"
        "东林党数十名大臣联名上疏，痛陈阉党之祸，力请圣上彻查余孽、"
        "还朝堂清明。奏疏言辞激烈，句句锥心。\n\n"
        "为首者言：'阉竖虽去，余毒未消。若不痛加惩创，恐养痈遗患，"
        "贻害社稷。伏乞圣裁！'"
    ),
    choices=[
        ScriptChoice(
            label="准予弹劾",
            description="准许东林党所请，下旨彻查阉党余孽。",
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="魏忠贤",
                sub_action=PersonnelAction.DISMISS,
            )],
        ),
        ScriptChoice(
            label="驳回奏折",
            description="以'事已了结、不宜再究'为由驳回。东林党恐更加不满。",
            decrees=[],
        ),
    ],
))

_register(ScriptEvent(
    script_id="shaanxi-famine-memorial",
    trigger_year=1628,
    trigger_month=3,
    title="陕西大旱·饥民请愿",
    is_blocking=True,
    rich_description=(
        "**崇祯元年，三月。**\n\n"
        "臣陕西巡抚奏：今春以来，雨泽未沾，赤地千里，饥民遍野，哀鸿遍地。"
        "臣日夜焦虑，伏乞圣裁。\n\n"
        "据查：延安、庆阳、平凉诸府，斗米价至银一两二钱，"
        "百姓剥树皮、掘草根以充饥，饿殍载道。更有饥民聚众请愿，"
        "拦截官道，哭声震天。\n\n"
        "若不急加赈济，恐酿大变。臣斗胆请旨：一则拨银赈灾，"
        "二则减免当年赋税，以纾民困。伏惟圣裁。"
    ),
    choices=[
        ScriptChoice(
            label="拨银赈灾",
            description="从国库拨出银两赈济陕西灾民，安定民心。然国库本已捉襟见肘。",
            decrees=[StructuredDecree(
                type=DecreeType.DISASTER_RELIEF,
                target="陕西",
            )],
        ),
        ScriptChoice(
            label="令地方自筹",
            description="令陕西地方官府自行筹措赈灾银两。虽保住国库，但恐激化民怨。",
            decrees=[],
        ),
        ScriptChoice(
            label="减免赋税",
            description="减免陕西及周边地区当年赋税，与民休息。虽损财政收入，但可缓和民情。",
            decrees=[StructuredDecree(type=DecreeType.TAX_DECREASE)],
        ),
    ],
))
