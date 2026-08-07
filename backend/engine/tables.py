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
