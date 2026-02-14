from __future__ import annotations

import math
from pydantic import BaseModel, Field

from .enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    PersonnelAction, EventUrgency, MinisterStatus,
)


# ── Faction ──────────────────────────────────────────────

class Faction(BaseModel):
    name: str
    satisfaction: int = Field(ge=0, le=100)
    influence: int = Field(ge=0, le=100)
    rebellion_risk: int = Field(ge=0, le=100)


# ── Minister ─────────────────────────────────────────────

class MinisterAbilities(BaseModel):
    civil: int = Field(default=0, ge=0, le=100)
    military: int = Field(default=0, ge=0, le=100)
    diplomacy: int = Field(default=0, ge=0, le=100)


class Minister(BaseModel):
    name: str
    faction: str
    personality_tags: list[str] = Field(default_factory=list, max_length=3)
    abilities: MinisterAbilities = Field(default_factory=MinisterAbilities)
    status: MinisterStatus = MinisterStatus.ACTIVE


# ── Region ───────────────────────────────────────────────

class Region(BaseModel):
    name: str
    stability: int = Field(ge=0, le=100)
    garrison: int = Field(ge=0)
    control: RegionControl = RegionControl.COURT
    threat: RegionThreat = RegionThreat.NONE
    tax_contribution: TaxContribution = TaxContribution.MEDIUM
    civil_morale: int = Field(default=50, ge=0, le=100)
    rebellion_risk: int = Field(default=10, ge=0, le=100)
    tax_rate: float = Field(default=0.5, ge=0, le=1)
    tax_collected: int = Field(default=0, ge=0)
    disaster_level: int = Field(default=0, ge=0, le=100)


# ── Decree ───────────────────────────────────────────────

class StructuredDecree(BaseModel):
    type: DecreeType
    target: str | None = None
    sub_action: PersonnelAction | None = None
    parameters: dict | None = None


class DebateMinister(BaseModel):
    name: str
    faction: str
    position_summary: str = Field(max_length=50)


class DebateResult(BaseModel):
    debate_text: str
    minister_a: DebateMinister
    minister_b: DebateMinister
    option_a: StructuredDecree
    option_b: StructuredDecree
    keywords: list[str] = Field(default_factory=list, max_length=5)


# ── Event ────────────────────────────────────────────────

class EventChoice(BaseModel):
    label: str
    description: str = ""
    decrees: list[StructuredDecree] = Field(default_factory=list)


class GameEvent(BaseModel):
    name: str
    description: str = ""
    urgency: EventUrgency = EventUrgency.LOW
    triggered_year: int
    triggered_month: int
    rich_description: str = ""
    choices: list[EventChoice] = Field(default_factory=list)
    is_scripted: bool = False
    script_id: str | None = None


# ── History ──────────────────────────────────────────────

class HistoryEntry(BaseModel):
    year: int
    month: int
    decree_type: str
    decree_desc: str = ""
    delta: dict = Field(default_factory=dict)
    narrative: str = ""


# ── GameTime ─────────────────────────────────────────────

class GameTime(BaseModel):
    year: int = 1627
    month: int = 1
    era_name: str = "天启"
    era_year: int = 7


# ── GameState ────────────────────────────────────────────

class GameState(BaseModel):
    time: GameTime = Field(default_factory=GameTime)
    # resources (0~200)
    treasury: int = 100
    population: int = 100
    military_supply: int = 80
    # indicators (0~100)
    civil_morale: int = 60
    military_morale: int = 70
    court_prestige: int = 75
    # entities
    factions: list[Faction] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    ministers: list[Minister] = Field(default_factory=list)
    active_events: list[GameEvent] = Field(default_factory=list)
    history_log: list[HistoryEntry] = Field(default_factory=list)
    decree_count: int = 0
    event_cooldowns: dict[str, int] = Field(default_factory=dict)
    resolved_script_ids: set[str] = Field(default_factory=set)


# ── DecreeResponse ───────────────────────────────────────

class DecreeResponse(BaseModel):
    state: GameState
    delta: dict = Field(default_factory=dict)
    attribution: dict = Field(default_factory=dict)
    narrative: str = ""
    newly_triggered_events: list[str] = Field(default_factory=list)
    game_time: GameTime = Field(default_factory=GameTime)
    game_over: dict | None = None


# ── Error ────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict | None = None


# ── Factory ──────────────────────────────────────────────

INITIAL_FACTIONS = [
    Faction(name="东林党", satisfaction=72, influence=65, rebellion_risk=5),
    Faction(name="阉党残余", satisfaction=30, influence=25, rebellion_risk=15),
    Faction(name="勋贵集团", satisfaction=55, influence=40, rebellion_risk=8),
    Faction(name="边将势力", satisfaction=61, influence=50, rebellion_risk=12),
]

INITIAL_REGIONS = [
    Region(name="京畿", stability=80, garrison=50000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=75, rebellion_risk=10, tax_rate=0.50, tax_collected=40, disaster_level=10),
    Region(name="辽东", stability=40, garrison=30000, threat=RegionThreat.HOUJIN, tax_contribution=TaxContribution.LOW,
           civil_morale=35, rebellion_risk=55, tax_rate=0.30, tax_collected=12, disaster_level=40),
    Region(name="陕西", stability=25, garrison=5000, threat=RegionThreat.REBELLION, tax_contribution=TaxContribution.LOW,
           civil_morale=20, rebellion_risk=70, tax_rate=0.25, tax_collected=6, disaster_level=60),
    Region(name="江南", stability=85, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.HIGH,
           civil_morale=80, rebellion_risk=5, tax_rate=0.80, tax_collected=272, disaster_level=5),
    Region(name="中原", stability=60, garrison=15000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=55, rebellion_risk=20, tax_rate=0.50, tax_collected=60, disaster_level=15),
    Region(name="山东", stability=70, garrison=12000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=65, rebellion_risk=15, tax_rate=0.50, tax_collected=70, disaster_level=10),
    Region(name="云贵", stability=50, garrison=8000, threat=RegionThreat.TUSI, tax_contribution=TaxContribution.LOW,
           civil_morale=45, rebellion_risk=35, tax_rate=0.30, tax_collected=15, disaster_level=30),
    Region(name="川蜀", stability=65, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=60, rebellion_risk=15, tax_rate=0.50, tax_collected=65, disaster_level=10),
]

INITIAL_MINISTERS = [
    Minister(name="魏忠贤", faction="阉党残余", personality_tags=["贪婪", "阴狠", "善于结党"],
             abilities=MinisterAbilities(civil=60, military=20, diplomacy=40)),
    Minister(name="徐光启", faction="东林党", personality_tags=["务实", "博学", "开明"],
             abilities=MinisterAbilities(civil=90, military=30, diplomacy=70)),
    Minister(name="孙承宗", faction="边将势力", personality_tags=["刚烈", "忠诚", "善战"],
             abilities=MinisterAbilities(civil=50, military=95, diplomacy=60)),
    Minister(name="袁崇焕", faction="边将势力", personality_tags=["刚烈", "自负", "善守"],
             abilities=MinisterAbilities(civil=30, military=90, diplomacy=40)),
    Minister(name="周延儒", faction="东林党", personality_tags=["圆滑", "善辩", "投机"],
             abilities=MinisterAbilities(civil=70, military=20, diplomacy=80)),
    Minister(name="温体仁", faction="勋贵集团", personality_tags=["阴狠", "善于钻营", "排异"],
             abilities=MinisterAbilities(civil=65, military=15, diplomacy=55)),
    Minister(name="卢象升", faction="边将势力", personality_tags=["忠诚", "刚烈", "清廉"],
             abilities=MinisterAbilities(civil=40, military=85, diplomacy=30)),
    Minister(name="杨嗣昌", faction="勋贵集团", personality_tags=["务实", "善谋", "优柔"],
             abilities=MinisterAbilities(civil=75, military=60, diplomacy=65)),
]


def create_initial_state() -> GameState:
    state = GameState(
        time=GameTime(year=1627, month=10, era_name="天启", era_year=7),
        treasury=100, population=100, military_supply=80,
        civil_morale=60, military_morale=70, court_prestige=75,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=[m.model_copy() for m in INITIAL_MINISTERS],
    )
    from engine.core import inject_script_events
    inject_script_events(state)
    return state


# ── Clamping ─────────────────────────────────────────────

def clamp_resource(v: int) -> int:
    return max(0, min(200, math.floor(v)))


def clamp_indicator(v: int) -> int:
    return max(0, min(100, math.floor(v)))


def clamp_garrison(v: int) -> int:
    return max(0, math.floor(v))


def clamp_state(state: GameState) -> None:
    state.treasury = clamp_resource(state.treasury)
    state.population = clamp_resource(state.population)
    state.military_supply = clamp_resource(state.military_supply)
    state.civil_morale = clamp_indicator(state.civil_morale)
    state.military_morale = clamp_indicator(state.military_morale)
    state.court_prestige = clamp_indicator(state.court_prestige)
    for f in state.factions:
        f.satisfaction = clamp_indicator(f.satisfaction)
        f.influence = clamp_indicator(f.influence)
        f.rebellion_risk = clamp_indicator(f.rebellion_risk)
    for r in state.regions:
        r.stability = clamp_indicator(r.stability)
        r.garrison = clamp_garrison(r.garrison)
        r.civil_morale = clamp_indicator(r.civil_morale)
        r.rebellion_risk = clamp_indicator(r.rebellion_risk)
        r.tax_rate = round(max(0.0, min(1.0, r.tax_rate)), 2)
        r.tax_collected = max(0, math.floor(r.tax_collected))
        r.disaster_level = clamp_indicator(r.disaster_level)
    for m in state.ministers:
        m.abilities.civil = clamp_indicator(m.abilities.civil)
        m.abilities.military = clamp_indicator(m.abilities.military)
        m.abilities.diplomacy = clamp_indicator(m.abilities.diplomacy)
