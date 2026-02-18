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

# 8 types × 6 fields: treasury, population, military_supply, civil_morale, military_morale, court_prestige
DECREE_EFFECTS: dict[DecreeType, dict[str, int]] = {
    DecreeType.TAX_INCREASE:      {"treasury": 15, "population": 0,  "military_supply": 0,   "civil_morale": -8,  "military_morale": 0,   "court_prestige": 0},
    DecreeType.TAX_DECREASE:      {"treasury": -10,"population": 0,  "military_supply": 0,   "civil_morale": 6,   "military_morale": 0,   "court_prestige": -3},
    DecreeType.RECRUIT_TROOPS:    {"treasury": -20,"population": -5, "military_supply": 15,  "civil_morale": -3,  "military_morale": 8,   "court_prestige": 0},
    DecreeType.DISBAND_TROOPS:    {"treasury": 5,  "population": 3,  "military_supply": -10, "civil_morale": 2,   "military_morale": -10, "court_prestige": -5},
    DecreeType.PERSONNEL:         {"treasury": -5, "population": 0,  "military_supply": 0,   "civil_morale": 0,   "military_morale": 0,   "court_prestige": 5},
    DecreeType.DIPLOMACY:         {"treasury": -10,"population": 0,  "military_supply": 0,   "civil_morale": 0,   "military_morale": 3,   "court_prestige": 8},
    DecreeType.DISASTER_RELIEF:   {"treasury": -30,"population": 5,  "military_supply": 0,   "civil_morale": 12,  "military_morale": 0,   "court_prestige": 5},
    DecreeType.HARSH_PUNISHMENT:  {"treasury": 0,  "population": -3, "military_supply": 0,   "civil_morale": -10, "military_morale": 5,   "court_prestige": 3},
}

# 4 factions × 8 decree types
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
    "边将势力": {
        DecreeType.TAX_INCREASE: 3,   DecreeType.TAX_DECREASE: -5,  DecreeType.RECRUIT_TROOPS: 10,
        DecreeType.DISBAND_TROOPS: -12, DecreeType.PERSONNEL: -3,   DecreeType.DIPLOMACY: 8,
        DecreeType.DISASTER_RELIEF: 0, DecreeType.HARSH_PUNISHMENT: 5,
    },
}

# Preconditions: field, operator, threshold
DECREE_PRECONDITIONS: dict[DecreeType, list[tuple[str, str, int]]] = {
    DecreeType.TAX_INCREASE:     [("civil_morale", ">", 10)],
    DecreeType.TAX_DECREASE:     [("treasury", ">", 20)],
    DecreeType.RECRUIT_TROOPS:   [("treasury", ">=", 20), ("population", ">=", 10)],
    DecreeType.DISBAND_TROOPS:   [("military_supply", ">", 10)],
    DecreeType.PERSONNEL:        [("court_prestige", ">", 10)],
    DecreeType.DIPLOMACY:        [("treasury", ">=", 10)],
    DecreeType.DISASTER_RELIEF:  [("treasury", ">=", 30)],
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
    DecreeType.TAX_INCREASE:     "民心不足，恐激民变（需要民心>10，当前{civil_morale}）",
    DecreeType.TAX_DECREASE:     "国库不足，无力减税（需要钱粮>20，当前{treasury}）",
    DecreeType.RECRUIT_TROOPS:   "钱粮或人口不足，无法征兵（需要钱粮≥20且人口≥10）",
    DecreeType.DISBAND_TROOPS:   "军备不足（需要军备>10，当前{military_supply}）",
    DecreeType.PERSONNEL:        "朝廷威望不足（需要威望>10，当前{court_prestige}）",
    DecreeType.DIPLOMACY:        "国库不足，无力外交（需要钱粮≥10，当前{treasury}）",
    DecreeType.DISASTER_RELIEF:  "国库不足，无法赈灾（需要钱粮≥30，当前{treasury}）",
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
    "global.treasury":            {"type": "int"},
    "global.population":          {"type": "int"},
    "global.military_supply":     {"type": "int"},
    "global.civil_morale":        {"type": "int"},
    "global.military_morale":     {"type": "int"},
    "global.court_prestige":      {"type": "int"},
    "minister.*.loyalty":         {"type": "int"},
    "minister.*.status":          {"type": "str", "valid": {"active", "idle", "removed"}},
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
})
