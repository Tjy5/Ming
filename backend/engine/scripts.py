from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from models.game import GameState

from models.game import StructuredDecree
from models.enums import DecreeType, PersonnelAction, MinisterStatus


@dataclass
class ScriptChoice:
    label: str
    description: str
    decrees: list[StructuredDecree] = field(default_factory=list)
    loyalty_effects: list[tuple[str, int]] = field(default_factory=list)
    state_effects: dict[str, int] = field(default_factory=dict)


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
            loyalty_effects=[("魏忠贤", -30), ("徐光启", 10)],
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
            loyalty_effects=[("魏忠贤", -15)],
        ),
    ],
))


def _faction_field(state, faction_name: str, field: str) -> int | None:
    f = next((f for f in state.factions if f.name == faction_name), None)
    return getattr(f, field) if f else None


def _region_field(state, region_name: str, field: str) -> int | None:
    r = next((r for r in state.regions if r.name == region_name), None)
    return getattr(r, field) if r else None


def _minister_active(state, name: str) -> bool:
    m = next((m for m in state.ministers if m.name == name), None)
    return m is not None and m.status == MinisterStatus.ACTIVE


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


# ── Phase 3: Extended Historical Scripts (1628-1630) ───

_register(ScriptEvent(
    script_id="rebel-wangjiaying",
    trigger_year=1628,
    trigger_month=6,
    title="流寇初起·王嘉胤举旗",
    is_blocking=True,
    condition=lambda s: (_v := _region_field(s, "陕西", "stability")) is not None and _v < 40,
    rich_description=(
        "**崇祯元年，六月。**\n\n"
        "陕西连年大旱，饥民遍野。府谷人王嘉胤聚众起事，"
        "号称'替天行道'，流民纷起响应，声势日壮。\n\n"
        "地方急报：贼众裹粮疾走，焚掠仓廒，县城守军不敢出战。"
        "若再失控，关中粮道恐将断绝。\n\n"
        "朝廷当如何应对？"
    ),
    choices=[
        ScriptChoice(
            label="调兵围剿",
            description="消耗钱粮军备但可遏制流寇蔓延。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
        ),
        ScriptChoice(
            label="招抚安置",
            description="耗费国库但安抚民心，从根源化解民变。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="令地方自行处置",
            description="朝廷不直接介入，令地方官自行弹压。然恐贻误战机。",
            decrees=[],
            state_effects={"region.陕西.stability": -10},
        ),
    ],
))

_register(ScriptEvent(
    script_id="ningyuan-mutiny",
    trigger_year=1628,
    trigger_month=7,
    title="宁远兵变",
    is_blocking=False,
    condition=lambda s: s.military_morale < 50 and s.treasury < 60,
    rich_description=(
        "**崇祯元年，七月。**\n\n"
        "辽东宁远驻军因欠饷日久，夜聚鼓噪，军门连发急报。"
        "守将言：若再无银粮，恐边军离散，堡寨难守。\n\n"
        "辽左前线一旦失序，后金骑兵可乘虚南下。"
        "朝廷须速作决断。"
    ),
    choices=[
        ScriptChoice(
            label="拨银补饷",
            description="加税筹饷，先稳住边军战意。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
        ),
        ScriptChoice(
            label="严惩首恶",
            description="杀一儆百，以军法惩处闹饷首领。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
        ),
        ScriptChoice(
            label="安抚许诺",
            description="许以来月补发，暂缓军心。然边将势力恐对朝廷更加不满。",
            decrees=[],
            state_effects={"faction.边将势力.satisfaction": -10},
        ),
    ],
))

_register(ScriptEvent(
    script_id="jisi-invasion",
    trigger_year=1629,
    trigger_month=10,
    title="己巳之变·皇太极入寇",
    is_blocking=True,
    rich_description=(
        "**崇祯二年，十月。**\n\n"
        "后金大汗皇太极率精骑绕道蒙古，突破长城隘口，"
        "直逼京畿。蓟镇烽火昼夜不绝，京师震动。\n\n"
        "廷臣争论不休：或请速战，或请和议，或请坚壁清野。"
        "皇城内外人心惶惶，仓卒调度稍有失当，便可能酿成大祸。\n\n"
        "天子当如何应对这场突如其来的危机？"
    ),
    choices=[
        ScriptChoice(
            label="急召天下勤王",
            description="集中各路兵马勤王，以战止战。辽东、京畿防线将受冲击。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.辽东.stability": -20,
                "region.京畿.stability": -20,
                "global.military_morale": 10,
            },
        ),
        ScriptChoice(
            label="固守京城待援",
            description="紧闭城门，坚壁清野，等待各路援军。然京畿百姓将遭涂炭。",
            decrees=[],
            state_effects={
                "region.京畿.stability": -15,
                "global.court_prestige": -10,
            },
        ),
        ScriptChoice(
            label="命袁崇焕回援",
            description="急令袁崇焕率辽东精锐回师勤王，试图以外交拖延后金攻势。",
            decrees=[StructuredDecree(type=DecreeType.DIPLOMACY, target="后金")],
        ),
    ],
))

_register(ScriptEvent(
    script_id="yuan-chonghuan-arrest",
    trigger_year=1629,
    trigger_month=12,
    title="袁崇焕下狱",
    is_blocking=True,
    condition=lambda s: "jisi-invasion" in s.resolved_script_ids,
    rich_description=(
        "**崇祯二年，十二月。**\n\n"
        "京师解围后，朝野对袁崇焕毁誉并起。"
        "有弹劾其通敌卖国者，有言其擅杀毛文龙、纵敌入关者，"
        "亦有力保其忠勇者。风闻交织，真伪难辨。\n\n"
        "若轻断重臣，恐伤军心；若久拖不决，又损朝廷威信。"
        "圣裁所向，将决定边防命脉。"
    ),
    choices=[
        ScriptChoice(
            label="逮捕袁崇焕",
            description="先行收系问罪，以平京师汹汹舆情。边将势力恐大为震动。",
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="袁崇焕",
                sub_action=PersonnelAction.DISMISS,
            )],
            loyalty_effects=[("袁崇焕", -50)],
            state_effects={
                "faction.边将势力.satisfaction": -25,
                "faction.边将势力.rebellion_risk": 20,
            },
        ),
        ScriptChoice(
            label="力排众议，保袁崇焕",
            description="顶住压力为袁崇焕辩护。阉党残余与勋贵集团恐更加不满。",
            decrees=[],
            loyalty_effects=[("袁崇焕", 20)],
            state_effects={
                "faction.阉党残余.satisfaction": -15,
                "faction.勋贵集团.satisfaction": -15,
                "global.court_prestige": -10,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="li-zicheng-joins",
    trigger_year=1630,
    trigger_month=3,
    title="陕西大起义·李自成从军",
    is_blocking=False,
    condition=lambda s: (_v := _region_field(s, "陕西", "stability")) is not None and _v < 30,
    rich_description=(
        "**崇祯三年，三月。**\n\n"
        "陕西驿递裁汰，失业驿卒与饥民并起。"
        "米脂人李自成弃役从伍，投身闯军，渐露锋芒。\n\n"
        "地方官奏称：若任其流聚，陕北山川易守难攻，"
        "势必尾大不掉。流寇之势已非一县一府所能弹压。"
    ),
    choices=[
        ScriptChoice(
            label="重兵围剿",
            description="调集重兵围剿，力图将流寇扼杀于萌芽。然耗费甚巨。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.陕西.stability": 10,
                "global.treasury": -20,
            },
        ),
        ScriptChoice(
            label="分化瓦解",
            description="与蒙古通好以减少多线压力，腾出手来对付流寇。",
            decrees=[StructuredDecree(type=DecreeType.DIPLOMACY, target="蒙古")],
        ),
        ScriptChoice(
            label="置之不理",
            description="朝廷无暇西顾，任由地方自行应对。陕西与中原恐将动荡加剧。",
            decrees=[],
            state_effects={
                "region.陕西.stability": -15,
                "region.中原.stability": -10,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="sun-chengzong-recovery",
    trigger_year=1630,
    trigger_month=5,
    title="孙承宗收复遵化四城",
    is_blocking=False,
    condition=lambda s: _minister_active(s, "孙承宗") and s.military_supply > 40,
    rich_description=(
        "**崇祯三年，五月。**\n\n"
        "老将孙承宗率军反攻，连克遵化、永平、迁安、滦州四城，"
        "后金残部退出关内。辽东军民士气大振。\n\n"
        "然追击深入恐有伏兵之险，见好就收亦可巩固战果。"
        "陛下当如何决断？"
    ),
    choices=[
        ScriptChoice(
            label="乘胜追击",
            description="趁后金立足未稳，挥师追击，力图扩大战果。然耗费军资甚巨。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.辽东.stability": 15,
                "global.military_morale": 10,
                "global.treasury": -25,
            },
        ),
        ScriptChoice(
            label="见好就收、巩固防线",
            description="收复四城已是大功，当务之急是巩固防线、休整军队。",
            decrees=[],
            state_effects={
                "region.辽东.stability": 10,
                "global.court_prestige": 5,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="dalinghe-prelude",
    trigger_year=1630,
    trigger_month=9,
    title="大凌河之围前奏",
    is_blocking=False,
    condition=lambda s: (_v := _region_field(s, "辽东", "stability")) is not None and _v < 40,
    rich_description=(
        "**崇祯三年，九月。**\n\n"
        "后金蓄势准备围攻大凌河，辽东局势再度紧张。"
        "前线请示是增援固守还是收缩防线。\n\n"
        "辽东诸堡互为犄角，一处失守便可能牵动全局。"
        "兵部连夜会同督抚上奏，请陛下速定方略。"
    ),
    choices=[
        ScriptChoice(
            label="增援大凌河",
            description="增兵固守大凌河，消耗军备但可稳住辽东防线。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "global.military_supply": -15,
                "region.辽东.stability": 5,
            },
        ),
        ScriptChoice(
            label="收缩防线",
            description="放弃外围据点，收缩兵力于核心堡寨。辽东稳定将受损但可节约军费。",
            decrees=[StructuredDecree(type=DecreeType.DISBAND_TROOPS)],
            state_effects={"region.辽东.stability": -10},
        ),
    ],
))
