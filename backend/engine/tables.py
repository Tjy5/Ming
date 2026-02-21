from models.enums import DecreeType

DECREE_LABELS: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE: "加税",
    DecreeType.TAX_DECREASE: "减税",
    DecreeType.RECRUIT_TROOPS: "增兵",
    DecreeType.DISBAND_TROOPS: "裁兵",
    DecreeType.PERSONNEL: "任免",
    DecreeType.DIPLOMACY: "外交",
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
DECREE_EFFECTS: dict[DecreeType, dict[str, int]] = {
    DecreeType.TAX_INCREASE:      {"national_treasury": 4,  "grain": 12,  "population": 0,    "military_strength": 0,   "civil_morale": -5,  "military_morale": 0,   "court_prestige": 0},
    DecreeType.TAX_DECREASE:      {"national_treasury": -3, "grain": -8,  "population": 0,    "military_strength": 0,   "civil_morale": 6,   "military_morale": 0,   "court_prestige": -3},
    DecreeType.RECRUIT_TROOPS:    {"national_treasury": -4, "grain": -15, "population": -750, "military_strength": 8,   "civil_morale": -3,  "military_morale": 8,   "court_prestige": 0},
    DecreeType.DISBAND_TROOPS:    {"national_treasury": 2,  "grain": 6,   "population": 450,  "military_strength": -6,  "civil_morale": 2,   "military_morale": -10, "court_prestige": -5},
    DecreeType.PERSONNEL:         {"national_treasury": -1, "grain": 0,   "population": 0,    "military_strength": 0,   "civil_morale": 0,   "military_morale": 0,   "court_prestige": 5},
    DecreeType.DIPLOMACY:         {"national_treasury": -2, "grain": -5,  "population": 0,    "military_strength": 0,   "civil_morale": 0,   "military_morale": 3,   "court_prestige": 8},
    DecreeType.DISASTER_RELIEF:   {"national_treasury": -3, "grain": -25, "population": 450,  "military_strength": 0,   "civil_morale": 10,  "military_morale": 0,   "court_prestige": 4},
    DecreeType.HARSH_PUNISHMENT:  {"national_treasury": 0,  "grain": 0,   "population": -450, "military_strength": 0,   "civil_morale": -10, "military_morale": 5,   "court_prestige": 3},
}

# 8 factions × 8 decree types
FACTION_STANCE: dict[str, dict[DecreeType, int]] = {
    "东林党": {
        DecreeType.TAX_INCREASE: -12, DecreeType.TAX_DECREASE: 8,   DecreeType.RECRUIT_TROOPS: -5,
        DecreeType.DISBAND_TROOPS: 3, DecreeType.PERSONNEL: 6,      DecreeType.DIPLOMACY: 4,
        DecreeType.DISASTER_RELIEF: 10, DecreeType.HARSH_PUNISHMENT: -15,
    },
    "阉党残余": {
        DecreeType.TAX_INCREASE: 5,   DecreeType.TAX_DECREASE: -8,  DecreeType.RECRUIT_TROOPS: 3,
        DecreeType.DISBAND_TROOPS: -3, DecreeType.PERSONNEL: -8,    DecreeType.DIPLOMACY: -5,
        DecreeType.DISASTER_RELIEF: -3, DecreeType.HARSH_PUNISHMENT: 12,
    },
    "勋贵集团": {
        DecreeType.TAX_INCREASE: -3,  DecreeType.TAX_DECREASE: 5,   DecreeType.RECRUIT_TROOPS: -8,
        DecreeType.DISBAND_TROOPS: 8, DecreeType.PERSONNEL: 3,      DecreeType.DIPLOMACY: 6,
        DecreeType.DISASTER_RELIEF: 2, DecreeType.HARSH_PUNISHMENT: -5,
    },
    "辽东边将": {
        DecreeType.TAX_INCREASE: 3,   DecreeType.TAX_DECREASE: -5,  DecreeType.RECRUIT_TROOPS: 10,
        DecreeType.DISBAND_TROOPS: -12, DecreeType.PERSONNEL: -3,   DecreeType.DIPLOMACY: 8,
        DecreeType.DISASTER_RELIEF: 0, DecreeType.HARSH_PUNISHMENT: 5,
    },
    "中原剿匪系": {
        DecreeType.TAX_INCREASE: 2,   DecreeType.TAX_DECREASE: -6,  DecreeType.RECRUIT_TROOPS: 9,
        DecreeType.DISBAND_TROOPS: -10, DecreeType.PERSONNEL: 4,    DecreeType.DIPLOMACY: -2,
        DecreeType.DISASTER_RELIEF: 2, DecreeType.HARSH_PUNISHMENT: 8,
    },
    "温体仁派": {
        DecreeType.TAX_INCREASE: 4,   DecreeType.TAX_DECREASE: -6,  DecreeType.RECRUIT_TROOPS: 1,
        DecreeType.DISBAND_TROOPS: -2, DecreeType.PERSONNEL: 9,     DecreeType.DIPLOMACY: -4,
        DecreeType.DISASTER_RELIEF: -4, DecreeType.HARSH_PUNISHMENT: 10,
    },
    "周延儒派": {
        DecreeType.TAX_INCREASE: -4,  DecreeType.TAX_DECREASE: 4,   DecreeType.RECRUIT_TROOPS: -2,
        DecreeType.DISBAND_TROOPS: 2, DecreeType.PERSONNEL: 8,      DecreeType.DIPLOMACY: 5,
        DecreeType.DISASTER_RELIEF: 3, DecreeType.HARSH_PUNISHMENT: -8,
    },
    "中立派": {
        DecreeType.TAX_INCREASE: -2,  DecreeType.TAX_DECREASE: 2,   DecreeType.RECRUIT_TROOPS: 2,
        DecreeType.DISBAND_TROOPS: 1, DecreeType.PERSONNEL: 1,      DecreeType.DIPLOMACY: 3,
        DecreeType.DISASTER_RELIEF: 5, DecreeType.HARSH_PUNISHMENT: -3,
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

REGION_NAMES = {"京畿", "辽东", "陕西", "江南", "中原", "山东", "云贵", "川蜀"}
DIPLOMACY_TARGETS = {"后金", "蒙古", "朝鲜"}

PRECONDITION_MESSAGES: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE:     "民心过低，仓促加税恐激民变（需要民心>5，当前{civil_morale}）",
    DecreeType.TAX_DECREASE:     "国库存银不足，无力减税（需要国库>8万两，当前{national_treasury}）",
    DecreeType.RECRUIT_TROOPS:   "银粮或人口不足，无法征兵（需要国库≥8万两且人口≥1200万人，当前{national_treasury}/{population}）",
    DecreeType.DISBAND_TROOPS:   "军力不足（需要军力>8万人，当前{military_strength}）",
    DecreeType.PERSONNEL:        "朝廷威望不足（需要威望>10，当前{court_prestige}）",
    DecreeType.DIPLOMACY:        "国库存银不足，无力外交（需要国库≥5万两，当前{national_treasury}）",
    DecreeType.DISASTER_RELIEF:  "银粮不足，无法赈灾（需要国库≥6万两且粮储≥120万石，当前{national_treasury}/{grain}）",
    DecreeType.HARSH_PUNISHMENT: "朝廷威望不足（需要威望>5，当前{court_prestige}）",
}


TARGET_MISSING_MESSAGES: dict[DecreeType, str] = {
    DecreeType.DISASTER_RELIEF: "赈灾需要指定目标区域",
    DecreeType.PERSONNEL: "任免需要指定目标人物和任免类型",
    DecreeType.DIPLOMACY: "外交需要指定目标（后金/蒙古/朝鲜）",
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
    "minister.*.status":          {"type": "str", "valid": {"active", "idle", "removed", "not_yet_entered"}},
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
    "region.*.threat":            {"type": "str", "valid": {"none", "后金", "民变", "土司", "海盗"}},
}

# Fields that SHALL NOT be modified by AI
SYSTEM_FIELDS = frozenset({
    "time", "decree_count", "history_log", "memorials",
    "memorial_cooldowns", "event_cooldowns", "resolved_script_ids",
    "loyalty_zero_triggered", "last_assembly", "last_assembly_month",
})

# Valid minister status transitions: (from, to)
VALID_STATUS_TRANSITIONS = frozenset({
    ("active", "idle"), ("active", "removed"),
    ("idle", "active"), ("idle", "removed"),
    ("not_yet_entered", "active"), ("not_yet_entered", "removed"),
    ("active", "on_mission"), ("on_mission", "active"), ("on_mission", "removed"),
})
