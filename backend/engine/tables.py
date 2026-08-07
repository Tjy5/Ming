from collections.abc import Callable

from models.enums import DecreeType

DECREE_LABELS: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE: "加征",
    DecreeType.TAX_DECREASE: "减赋",
    DecreeType.RECRUIT_TROOPS: "募兵",
    DecreeType.DISBAND_TROOPS: "裁军",
    DecreeType.PERSONNEL: "任免",
    DecreeType.DIPLOMACY: "通好",
    DecreeType.DISASTER_RELIEF: "赈灾",
    DecreeType.HARSH_PUNISHMENT: "严刑",
}

CONSECUTIVE_WAIT_THRESHOLD = 3
WAIT_PRESTIGE_PENALTY = 5
WAIT_MORALE_PENALTY = 1
PENDING_MEMORIAL_THRESHOLD = 5
PENDING_MEMORIAL_PRESTIGE_PENALTY = 3
APPOINT_LOYALTY_BONUS = 15
DISMISS_LOYALTY_PENALTY = 20
EXECUTION_SATISFACTION_PENALTY = 15
EXECUTION_REBELLION_RISK = 10

# 8 types × 7 fields: national_treasury, grain, population, military_strength, civil_morale, military_morale, court_prestige
# 阶段D 平衡基线（2026-08-07）：数值未调整——既有治理回归面（test_balance_mechanics
# 等 541 用例）全绿；通关性整体验证归 e2e（步骤 7），若暴露失衡再按表项校准并注明理由。
DECREE_EFFECTS: dict[DecreeType, dict[str, int]] = {
    DecreeType.TAX_INCREASE:      {"national_treasury": 4,  "grain": 12,  "population": 0,    "military_strength": 0,   "civil_morale": -5,  "military_morale": 0,   "court_prestige": 0},
    DecreeType.TAX_DECREASE:      {"national_treasury": -3, "grain": -8,  "population": 0,    "military_strength": 0,   "civil_morale": 6,   "military_morale": 0,   "court_prestige": -3},
    # 阶段D 平衡修复（e2e 暴露，主会话裁决 2026-08-07）：
    # - RECRUIT_TROOPS 粮 -15→-8：受威胁区域维稳成本与粮收入（约 12-18/月）匹配；
    # - DISASTER_RELIEF 粮 -25→-12：同上，避免赈灾被粮前置（>120）过早锁死。
    DecreeType.RECRUIT_TROOPS:    {"national_treasury": -4, "grain": -8,  "population": -30,  "military_strength": 8,   "civil_morale": -3,  "military_morale": 8,   "court_prestige": 0},
    DecreeType.DISBAND_TROOPS:    {"national_treasury": 2,  "grain": 6,   "population": 20,   "military_strength": -6,  "civil_morale": 2,   "military_morale": -10, "court_prestige": -5},
    DecreeType.PERSONNEL:         {"national_treasury": -1, "grain": 0,   "population": 0,    "military_strength": 0,   "civil_morale": 0,   "military_morale": 0,   "court_prestige": 5},
    DecreeType.DIPLOMACY:         {"national_treasury": -2, "grain": -5,  "population": 0,    "military_strength": 0,   "civil_morale": 0,   "military_morale": 3,   "court_prestige": 8},
    DecreeType.DISASTER_RELIEF:   {"national_treasury": -3, "grain": -12, "population": 25,   "military_strength": 0,   "civil_morale": 10,  "military_morale": 0,   "court_prestige": 4},
    DecreeType.HARSH_PUNISHMENT:  {"national_treasury": 0,  "grain": 0,   "population": -25,  "military_strength": 0,   "civil_morale": -10, "military_morale": 5,   "court_prestige": 3},
}

# 8 factions × 8 decree types（元末群雄立场）
FACTION_STANCE: dict[str, dict[DecreeType, int]] = {
    "淮西勋将": {
        DecreeType.TAX_INCREASE: 3,   DecreeType.TAX_DECREASE: -5,  DecreeType.RECRUIT_TROOPS: 10,
        DecreeType.DISBAND_TROOPS: -12, DecreeType.PERSONNEL: -3,   DecreeType.DIPLOMACY: 8,
        DecreeType.DISASTER_RELIEF: 0, DecreeType.HARSH_PUNISHMENT: 5,
    },
    "幕府文臣": {
        DecreeType.TAX_INCREASE: -12, DecreeType.TAX_DECREASE: 8,   DecreeType.RECRUIT_TROOPS: -5,
        DecreeType.DISBAND_TROOPS: 3, DecreeType.PERSONNEL: 6,      DecreeType.DIPLOMACY: 4,
        DecreeType.DISASTER_RELIEF: 10, DecreeType.HARSH_PUNISHMENT: -15,
    },
    "江南士绅": {
        DecreeType.TAX_INCREASE: -8,  DecreeType.TAX_DECREASE: 6,   DecreeType.RECRUIT_TROOPS: -3,
        DecreeType.DISBAND_TROOPS: 2, DecreeType.PERSONNEL: 2,      DecreeType.DIPLOMACY: 5,
        DecreeType.DISASTER_RELIEF: 8, DecreeType.HARSH_PUNISHMENT: -8,
    },
    "龙凤政权": {
        DecreeType.TAX_INCREASE: 2,   DecreeType.TAX_DECREASE: -2,  DecreeType.RECRUIT_TROOPS: 5,
        DecreeType.DISBAND_TROOPS: -5, DecreeType.PERSONNEL: 8,     DecreeType.DIPLOMACY: 6,
        DecreeType.DISASTER_RELIEF: 3, DecreeType.HARSH_PUNISHMENT: -5,
    },
    "汉政权": {
        DecreeType.TAX_INCREASE: 0,   DecreeType.TAX_DECREASE: 0,   DecreeType.RECRUIT_TROOPS: -10,
        DecreeType.DISBAND_TROOPS: 8, DecreeType.PERSONNEL: -2,     DecreeType.DIPLOMACY: 10,
        DecreeType.DISASTER_RELIEF: 0, DecreeType.HARSH_PUNISHMENT: -3,
    },
    "吴政权": {
        DecreeType.TAX_INCREASE: -2,  DecreeType.TAX_DECREASE: 2,   DecreeType.RECRUIT_TROOPS: -8,
        DecreeType.DISBAND_TROOPS: 6, DecreeType.PERSONNEL: 0,      DecreeType.DIPLOMACY: 10,
        DecreeType.DISASTER_RELIEF: 2, DecreeType.HARSH_PUNISHMENT: -2,
    },
    "元廷": {
        DecreeType.TAX_INCREASE: 3,   DecreeType.TAX_DECREASE: -3,  DecreeType.RECRUIT_TROOPS: -12,
        DecreeType.DISBAND_TROOPS: 10, DecreeType.PERSONNEL: -5,    DecreeType.DIPLOMACY: 8,
        DecreeType.DISASTER_RELIEF: -2, DecreeType.HARSH_PUNISHMENT: 3,
    },
    "东南群雄": {
        DecreeType.TAX_INCREASE: -3,  DecreeType.TAX_DECREASE: 3,   DecreeType.RECRUIT_TROOPS: -6,
        DecreeType.DISBAND_TROOPS: 5, DecreeType.PERSONNEL: 2,      DecreeType.DIPLOMACY: 12,
        DecreeType.DISASTER_RELIEF: 3, DecreeType.HARSH_PUNISHMENT: -4,
    },
}

# Preconditions: field, operator, threshold
DECREE_PRECONDITIONS: dict[DecreeType, list[tuple[str, str, int]]] = {
    DecreeType.TAX_INCREASE:     [("civil_morale", ">", 5)],
    DecreeType.TAX_DECREASE:     [("national_treasury", ">", 8)],
    DecreeType.RECRUIT_TROOPS:   [("national_treasury", ">=", 8), ("population", ">=", 1200)],
    DecreeType.DISBAND_TROOPS:   [("military_strength", ">", 8)],
    DecreeType.PERSONNEL:        [("court_prestige", ">", 10)],
    DecreeType.DIPLOMACY:        [("national_treasury", ">=", 5)],
    DecreeType.DISASTER_RELIEF:  [("national_treasury", ">=", 6), ("grain", ">=", 120)],
    DecreeType.HARSH_PUNISHMENT: [("court_prestige", ">", 5)],
}

DECREE_TARGET_REQUIRED: dict[DecreeType, str] = {
    DecreeType.DISASTER_RELIEF: "region",
    DecreeType.PERSONNEL: "person",
    DecreeType.DIPLOMACY: "diplomacy_target",
}

REGION_NAMES = {"应天", "太平", "镇江", "两淮", "杭州", "武昌", "平江", "大都"}
DIPLOMACY_TARGETS = {"龙凤政权", "汉政权", "吴政权", "元廷", "东南群雄"}

PRECONDITION_MESSAGES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE:     "民心浮动，仓促加征恐激变乱（需要民心>5，当前{civil_morale}）",
    DecreeType.TAX_DECREASE:     "府库存银不足，无力减赋（需要国库>8万两，当前{national_treasury}）",
    DecreeType.RECRUIT_TROOPS:   "银粮或丁口不足，难以募兵（需要国库≥8万两且丁口≥1200万，当前{national_treasury}/{population}）",
    DecreeType.DISBAND_TROOPS:   "军力单薄，不可再裁（需要军力>8万人，当前{military_strength}）",
    DecreeType.PERSONNEL:        "军府威望不足以服众（需要威望>10，当前{court_prestige}）",
    DecreeType.DIPLOMACY:        "府库存银不足，无力遣使（需要国库≥5万两，当前{national_treasury}）",
    DecreeType.DISASTER_RELIEF:  "银粮不足，难以赈济（需要国库≥6万两且粮储≥120万石，当前{national_treasury}/{grain}）",
    DecreeType.HARSH_PUNISHMENT: "军府威望不足，严刑恐失人心（需要威望>5，当前{court_prestige}）",
}


TARGET_MISSING_MESSAGES: dict[DecreeType, str] = {
    DecreeType.DISASTER_RELIEF: "赈灾需要指定目标区域",
    DecreeType.PERSONNEL: "任免需要指定目标人物和任免类型",
    DecreeType.DIPLOMACY: "通好需要指定目标（龙凤政权/汉政权/吴政权/元廷/东南群雄）",
}


# ── AI Freeform: writable fields whitelist ──────────────
# Pattern uses * as wildcard for entity names.
# type: "int" = delta applied via +=, "float" = delta via += then round(2), "str" = direct set.

WRITABLE_FIELDS: dict[str, dict] = {
    "global.national_treasury":   {"type": "int"},
    "global.imperial_treasury":   {"type": "int"},
    "global.grain":               {"type": "int"},
    "global.population":          {"type": "int"},
    "global.military_strength":   {"type": "int"},
    "global.civil_morale":        {"type": "int"},
    "global.military_morale":     {"type": "int"},
    "global.court_prestige":      {"type": "int"},
    "minister.*.loyalty":         {"type": "int"},
    "minister.*.status":          {"type": "str", "valid": {"active", "idle", "removed", "not_yet_entered", "on_mission"}},
    "minister.*.abilities.civil":     {"type": "int"},
    "minister.*.abilities.military":  {"type": "int"},
    "minister.*.abilities.diplomacy": {"type": "int"},
    "faction.*.satisfaction":     {"type": "int"},
    "faction.*.rebellion_risk":   {"type": "int"},
    "faction.*.influence":        {"type": "int"},
    "region.*.stability":         {"type": "int"},
    "region.*.civil_morale":      {"type": "int"},
    "region.*.rebellion_risk":    {"type": "int"},
    "region.*.garrison":          {"type": "int"},
    "region.*.disaster_level":    {"type": "int"},
    "region.*.tax_rate":          {"type": "float"},
    "region.*.control":           {"type": "str", "valid": {"朝廷", "失控", "沦陷"}},
    "region.*.threat":            {"type": "str", "valid": {"none", "元军", "汉军", "吴军", "民变", "土司", "海盗"}},
}

# Fields that SHALL NOT be modified by AI
SYSTEM_FIELDS = frozenset({
    "time", "phase", "decree_count", "history_log", "memorials",
    "memorial_cooldowns", "event_cooldowns", "resolved_script_ids",
    "loyalty_zero_triggered", "last_assembly", "last_assembly_month",
    # 阶段B：跑团引擎系统字段（篇章/回合/角色卡/成长记录）同样禁止治理 AI 修改
    "chapter", "chapter_turns", "character_sheets", "growth_log",
})

# Valid minister status transitions: (from, to)
VALID_STATUS_TRANSITIONS = frozenset({
    ("active", "idle"), ("active", "removed"),
    ("idle", "active"), ("idle", "removed"),
    ("not_yet_entered", "active"), ("not_yet_entered", "removed"),
    ("active", "on_mission"), ("on_mission", "active"), ("on_mission", "removed"),
})

# ── TRPG ↔ 治理数据互通（阶段D，design 第 3.1 节）─────────
# 政令类别 → 角色卡 modifier 键（键集与 trpg/modifiers.get_player_modifiers 一致）。
# other 类政令不修正（None）；culture 键预留（引擎当前无文教/基建类政令）。
DECREE_CATEGORY_MODIFIER_KEY: dict[str, str | None] = {
    "domestic": "domestic",
    "military": "military",
    "diplomacy": "diplomacy",
    "other": None,
}


# ── 数值区间概念框（B5：模型只理解区间语义）────────────────
# 档位语义仅用于 prompt 注入（描述层），不修改任何数值/机制。
# 升序（lt）：value < limit 命中，从低到高遍历，兜底最高档；用于"越低越危险"的指标。
# 降序（ge）：value >= limit 命中，从高到低遍历，兜底最低档；用于"越高越危险"的指标。
GLOBAL_BANDS: dict[str, list[tuple[str, int, str, str]]] = {
    "national_treasury": [
        ("lt", 5, "崩溃", "府库空虚，度支维艰"),
        ("lt", 15, "告急", "国库吃紧，入不敷出"),
        ("lt", 40, "吃紧", "银钱紧张，用度需谨慎"),
        ("lt", 70, "平稳", "财政稳健"),
        ("lt", 999, "充裕", "府库充盈"),
    ],
    "imperial_treasury": [
        ("lt", 3, "空虚", "内帑一空，宫中节用"),
        ("lt", 10, "紧张", "内帑不足，赏赉从简"),
        ("lt", 25, "平稳", "内帑充裕"),
        ("lt", 999, "充盈", "内帑丰盈，赏赉无碍"),
    ],
    "grain": [
        ("lt", 30, "断粮", "粮储见底，饥荒在即"),
        ("lt", 80, "紧张", "粮储不足，军民用度吃紧"),
        ("lt", 150, "平稳", "粮储尚足"),
        ("lt", 999, "丰盈", "粮储丰盈，仓廪充实"),
    ],
    "population": [
        ("lt", 1000, "凋敝", "户口凋零，十室九空"),
        ("lt", 1400, "疲敝", "人丁不旺，劳力短缺"),
        ("lt", 1800, "平稳", "户口平稳"),
        ("lt", 9999, "兴旺", "户口兴旺，丁壮充盈"),
    ],
    "military_strength": [
        ("lt", 10, "孱弱", "武备废弛，无兵可用"),
        ("lt", 20, "吃紧", "军力不足，防御堪忧"),
        ("lt", 35, "平稳", "军力尚可"),
        ("lt", 999, "强盛", "兵强马壮，雄视一方"),
    ],
    "civil_morale": [
        ("lt", 15, "崩溃", "民怨沸腾，流民四起"),
        ("lt", 35, "危急", "百姓怨声载道，骚动暗生"),
        ("lt", 60, "不稳", "百姓多有怨言"),
        ("lt", 80, "平稳", "民心尚安"),
        ("lt", 101, "稳固", "民心归附，箪食壶浆"),
    ],
    "military_morale": [
        ("lt", 20, "涣散", "士卒怨怼，逃逸频发"),
        ("lt", 40, "低落", "士气不振，号令难行"),
        ("lt", 65, "平稳", "军心稳定"),
        ("lt", 101, "昂扬", "士气高昂，愿效死力"),
    ],
    "court_prestige": [
        ("lt", 20, "扫地", "威权扫地，号令不行"),
        ("lt", 40, "低落", "威望受损，人心浮动"),
        ("lt", 65, "平稳", "威望尚隆"),
        ("lt", 101, "隆盛", "威望隆盛，四方景从"),
    ],
}

# 区域档位：stability/civil_morale 升序；rebellion_risk/disaster_level 降序（ge）。
REGION_BANDS: dict[str, list[tuple[str, int, str, str]]] = {
    "stability": [
        ("lt", 15, "崩溃", "秩序崩溃，盗匪横行"),
        ("lt", 35, "动荡", "局势动荡，官民离心"),
        ("lt", 60, "不稳", "治政不稳，隐患渐生"),
        ("lt", 80, "平稳", "治政有序"),
        ("lt", 101, "稳固", "政通人和，百姓安居"),
    ],
    "civil_morale": GLOBAL_BANDS["civil_morale"],
    "rebellion_risk": [
        ("ge", 70, "高危", "叛乱一触即发"),
        ("ge", 40, "上升", "反迹渐显，人心浮动"),
        ("ge", 20, "可控", "小有骚动，尚可弹压"),
        ("lt", 20, "低危", "地方安靖"),
    ],
    "disaster_level": [
        ("ge", 60, "大灾", "灾害肆虐，饿殍载道"),
        ("ge", 30, "灾情", "灾情蔓延，赈济不及"),
        ("ge", 10, "隐患", "灾象初显"),
        ("lt", 10, "安靖", "无灾无疫"),
    ],
}

# 危险档位判定（用于⚠标注与膨胀控制）：命中档位（label）视为危险则展开描述。
# 升序表取最低两档（如崩溃/告急），降序表取最高两档（如高危/上升、大灾/灾情）。
DANGEROUS_BAND_LABELS = {"崩溃", "告急", "空虚", "断粮", "凋敝", "疲敝", "孱弱", "危急",
                         "涣散", "低落", "扫地", "动荡", "高危", "上升", "大灾", "灾情",
                         "紧张"}

# ── 阈值硬性预警（B5：数值触达→系统强制注入叙事口径；只提示不 apply）──
# check 只读 state 返回 bool，禁止写状态（与 CHAIN_EVENTS 的 apply 职责分离）。
THRESHOLD_ALERTS: list[tuple[str, Callable[[object], bool], str]] = [
    (
        "民心崩溃预警",
        lambda s: s.civil_morale < 15,
        "民心濒临崩溃：叙事必须描述民怨沸腾、流民四起、盗匪横行，禁止描述歌舞升平或民心安泰",
    ),
    (
        "军心动摇预警",
        lambda s: s.military_morale < 20,
        "军心涣散：叙事必须描述士卒怨怼、逃逸频发，禁止描述士气高昂或军令严明",
    ),
    (
        "国库空虚预警",
        lambda s: s.national_treasury < 5,
        "国库空虚：叙事必须如实反映度支困窘、用度从简，禁止描述大兴土木或挥霍无度",
    ),
    (
        "叛乱高危预警",
        lambda s: any(f.rebellion_risk > 70 for f in s.factions),
        "派系叛乱风险高企：叙事必须反映朝局不稳、人心离析，禁止描述上下同欲",
    ),
    (
        "区域失稳预警",
        lambda s: any(r.stability < 15 for r in s.regions),
        "有区域秩序崩溃：叙事必须反映该区域动乱，禁止描述该地安居乐业",
    ),
]
