from __future__ import annotations

import math
from pydantic import BaseModel, Field

from .enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    PersonnelAction, EventUrgency,
)


# ── Faction ──────────────────────────────────────────────

class Faction(BaseModel):
    name: str
    satisfaction: int = Field(ge=0, le=100)
    influence: int = Field(ge=0, le=100)
    rebellion_risk: int = Field(ge=0, le=100)


# ── Region ───────────────────────────────────────────────

class Region(BaseModel):
    name: str
    stability: int = Field(ge=0, le=100)
    garrison: int = Field(ge=0)
    control: RegionControl = RegionControl.COURT
    threat: RegionThreat = RegionThreat.NONE
    tax_contribution: TaxContribution = TaxContribution.MEDIUM


# ── Event ────────────────────────────────────────────────

class GameEvent(BaseModel):
    name: str
    description: str = ""
    urgency: EventUrgency = EventUrgency.LOW
    triggered_year: int
    triggered_month: int


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
    year: int = 1
    month: int = 1


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
    active_events: list[GameEvent] = Field(default_factory=list)
    history_log: list[HistoryEntry] = Field(default_factory=list)
    decree_count: int = 0
    event_cooldowns: dict[str, int] = Field(default_factory=dict)


# ── Decree ───────────────────────────────────────────────

class StructuredDecree(BaseModel):
    type: DecreeType
    target: str | None = None
    sub_action: PersonnelAction | None = None
    parameters: dict | None = None


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
    Region(name="京畿", stability=80, garrison=50000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM),
    Region(name="辽东", stability=40, garrison=30000, threat=RegionThreat.HOUJIN, tax_contribution=TaxContribution.LOW),
    Region(name="陕西", stability=25, garrison=5000, threat=RegionThreat.REBELLION, tax_contribution=TaxContribution.LOW),
    Region(name="江南", stability=85, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.HIGH),
    Region(name="中原", stability=60, garrison=15000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM),
    Region(name="山东", stability=70, garrison=12000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM),
    Region(name="云贵", stability=50, garrison=8000, threat=RegionThreat.TUSI, tax_contribution=TaxContribution.LOW),
    Region(name="川蜀", stability=65, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM),
]


def create_initial_state() -> GameState:
    return GameState(
        time=GameTime(year=1, month=1),
        treasury=100, population=100, military_supply=80,
        civil_morale=60, military_morale=70, court_prestige=75,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
    )


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
