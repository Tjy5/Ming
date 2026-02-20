from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    PersonnelAction, EventUrgency, MinisterStatus, MemorialStatus, AssemblyPhase,
)

MAX_MINISTER_CONVERSATION_MESSAGES = 50


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
    loyalty: int = Field(default=50, ge=0, le=100)
    position: str = ""
    entry_year: int = 1627
    entry_month: int = Field(default=8, ge=1, le=12)
    historical_note: str = Field(default="", max_length=200)


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


# ── Memorial ────────────────────────────────────────────

class MemorialDraft(BaseModel):
    content: str
    suggested_decrees: list[StructuredDecree] = Field(default_factory=list)


class Memorial(BaseModel):
    id: str
    author_name: str
    author_faction: str
    title: str
    content: str
    suggested_decrees: list[StructuredDecree] = Field(default_factory=list)
    trigger_reason: str
    urgency: str
    created_year: int
    created_month: int
    status: MemorialStatus = MemorialStatus.PENDING


class MinisterReaction(BaseModel):
    minister_name: str
    faction: str
    reaction_type: str
    reaction_text: str
    loyalty_change: int


class FreeformResult(BaseModel):
    effects: dict[str, int | float | str] = Field(default_factory=dict)
    narrative: str = ""
    reactions: list[MinisterReaction] = Field(default_factory=list)
    rationale: str = ""
    new_events: list[dict] = Field(default_factory=list)


# ── Court Assembly ──────────────────────────────────────

class AssemblyParticipant(BaseModel):
    name: str
    faction: str
    position: str
    argument_text: str


class PolicySuggestion(BaseModel):
    title: str
    description: str
    related_decree: StructuredDecree
    supporter_names: list[str] = Field(default_factory=list)


class CourtAssembly(BaseModel):
    phase: AssemblyPhase = AssemblyPhase.IDLE
    topic: str = ""
    current_topic: str = ""
    decree_type: DecreeType | None = None
    participants: list[AssemblyParticipant] = Field(default_factory=list)
    petitions: list["AssemblyPetition"] = Field(default_factory=list)
    speeches: list["AssemblySpeech"] = Field(default_factory=list)
    votes: list["AssemblyVote"] = Field(default_factory=list)
    suggestions: list[PolicySuggestion] = Field(default_factory=list)
    debate_text: str = ""
    consensus: str = ""
    silenced: bool = False
    rage_used: bool = False
    silenced_factions: list[str] = Field(default_factory=list)
    final_decision: str | None = None


class AssemblyPetition(BaseModel):
    minister_name: str
    content: str
    urgency: Literal["高", "中", "低"] = "中"


class AssemblySpeech(BaseModel):
    minister_name: str
    faction: str
    content: str
    stance: Literal["赞成", "反对", "中立"] = "中立"


class AssemblyVote(BaseModel):
    minister_name: str
    vote: Literal["赞成", "反对", "弃权"] = "弃权"
    reason: str = ""


# ── Turn Summary ────────────────────────────────────────

class IndicatorTrend(BaseModel):
    name: str
    before: int
    after: int


class FactionChange(BaseModel):
    name: str
    satisfaction_before: int
    satisfaction_after: int
    rebellion_risk_before: int
    rebellion_risk_after: int


class RegionChange(BaseModel):
    name: str
    stability_before: int
    stability_after: int
    control_before: str
    control_after: str
    threat_before: str
    threat_after: str
    garrison_before: Optional[int] = None
    garrison_after: Optional[int] = None
    civil_morale_before: Optional[int] = None
    civil_morale_after: Optional[int] = None
    rebellion_risk_before: Optional[int] = None
    rebellion_risk_after: Optional[int] = None
    disaster_level_before: Optional[int] = None
    disaster_level_after: Optional[int] = None
    tax_collected_before: Optional[int] = None
    tax_collected_after: Optional[int] = None
    tax_rate_before: Optional[float] = None
    tax_rate_after: Optional[float] = None
    tax_contribution_before: Optional[str] = None
    tax_contribution_after: Optional[str] = None


class MinisterChange(BaseModel):
    name: str
    loyalty_before: int
    loyalty_after: int
    status_before: str
    status_after: str


class RegionDetail(BaseModel):
    region: str
    field: str
    delta: float
    source: str


class TurnSummary(BaseModel):
    year: int
    month: int
    era_name: str
    era_year: int
    commentary: str = ""
    major_events: list[str] = Field(default_factory=list)
    action_implications: list[str] = Field(default_factory=list)
    indicator_trends: list[IndicatorTrend] = Field(default_factory=list)
    faction_changes: list[FactionChange] = Field(default_factory=list)
    region_changes: list[RegionChange] = Field(default_factory=list)
    minister_changes: list[MinisterChange] = Field(default_factory=list)
    region_details: Optional[list[RegionDetail]] = None
    pending_memorials_count: int = 0


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
    loyalty_effects: list[tuple[str, int]] = Field(default_factory=list)
    state_effects: dict[str, int] = Field(default_factory=dict)


class GameEvent(BaseModel):
    name: str
    description: str = ""
    urgency: EventUrgency = EventUrgency.LOW
    triggered_year: int
    triggered_month: int
    rich_description: str = ""
    choices: list[EventChoice] = Field(default_factory=list)
    is_scripted: bool = False
    is_blocking: bool = False
    script_id: str | None = None
    historical_hint: str = ""


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


# ── ConversationMessage ──────────────────────────────────

class ConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: str


def _default_conversation_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GameState ────────────────────────────────────────────

class GameState(BaseModel):
    time: GameTime = Field(default_factory=GameTime)
    # resources (historical scales)
    national_treasury: int = Field(default=20, ge=0, le=10000)
    imperial_treasury: int = Field(default=10, ge=0, le=10000)
    grain: int = Field(default=500, ge=0, le=50000)
    population: int = Field(default=15000, ge=0, le=20000)
    military_strength: int = Field(default=40, ge=0, le=2000)
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
    memorials: list[Memorial] = Field(default_factory=list)
    memorial_cooldowns: dict[str, int] = Field(default_factory=dict)
    last_assembly: CourtAssembly | None = None
    loyalty_zero_triggered: set[str] = Field(default_factory=set)
    last_assembly_month: int = 0
    consecutive_waits: int = 0
    minister_conversations: dict[str, list[ConversationMessage]] = Field(default_factory=dict)

    @field_validator("minister_conversations", mode="before")
    @classmethod
    def _normalize_minister_conversations(cls, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        normalized: dict[str, list[dict]] = {}
        for minister_name, messages in value.items():
            if not isinstance(minister_name, str):
                continue
            if not isinstance(messages, list):
                normalized[minister_name] = []
                continue
            sliced = messages[-MAX_MINISTER_CONVERSATION_MESSAGES:]
            converted: list[dict] = []
            for idx, message in enumerate(sliced):
                if isinstance(message, ConversationMessage):
                    converted.append(message.model_dump())
                    continue
                if isinstance(message, dict):
                    role_raw = str(message.get("role", "assistant")).strip().lower()
                    role = role_raw if role_raw in {"user", "assistant"} else "assistant"
                    content = str(message.get("content", ""))
                    msg_id = str(message.get("id") or f"{minister_name}_{idx}_{uuid4().hex}")
                    timestamp = str(message.get("timestamp") or _default_conversation_timestamp())
                    converted.append({
                        "id": msg_id,
                        "role": role,
                        "content": content,
                        "timestamp": timestamp,
                    })
            normalized[minister_name] = converted
        return normalized

    def append_conversation_message(
        self,
        minister_name: str,
        role: Literal["user", "assistant"],
        content: str,
        message_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        history = self.minister_conversations.setdefault(minister_name, [])
        history.append(ConversationMessage(
            id=message_id or uuid4().hex,
            role=role,
            content=content,
            timestamp=timestamp or _default_conversation_timestamp(),
        ))
        if len(history) > MAX_MINISTER_CONVERSATION_MESSAGES:
            self.minister_conversations[minister_name] = history[-MAX_MINISTER_CONVERSATION_MESSAGES:]


# ── DecreeResponse ───────────────────────────────────────

class DecreeResponse(BaseModel):
    state: GameState
    delta: dict = Field(default_factory=dict)
    attribution: dict = Field(default_factory=dict)
    narrative: str = ""
    newly_triggered_events: list[str] = Field(default_factory=list)
    game_time: GameTime = Field(default_factory=GameTime)
    game_over: dict | None = None
    minister_reactions: list[MinisterReaction] = Field(default_factory=list)
    turn_summary: TurnSummary | None = None
    memorial_triggers: list[Memorial] = Field(default_factory=list)


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
    Faction(name="辽东边将", satisfaction=61, influence=50, rebellion_risk=12),
    Faction(name="中原剿匪系", satisfaction=58, influence=45, rebellion_risk=10),
    Faction(name="温体仁派", satisfaction=50, influence=35, rebellion_risk=8),
    Faction(name="周延儒派", satisfaction=55, influence=40, rebellion_risk=6),
    Faction(name="中立派", satisfaction=60, influence=25, rebellion_risk=3),
]

INITIAL_REGIONS = [
    Region(name="京畿", stability=80, garrison=50000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=75, rebellion_risk=10, tax_rate=0.50, tax_collected=88, disaster_level=10),
    Region(name="辽东", stability=45, garrison=30000, threat=RegionThreat.HOUJIN, tax_contribution=TaxContribution.LOW,
           civil_morale=35, rebellion_risk=55, tax_rate=0.30, tax_collected=16, disaster_level=40),
    Region(name="陕西", stability=35, garrison=5000, threat=RegionThreat.REBELLION, tax_contribution=TaxContribution.LOW,
           civil_morale=20, rebellion_risk=70, tax_rate=0.25, tax_collected=10, disaster_level=60),
    Region(name="江南", stability=85, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.HIGH,
           civil_morale=80, rebellion_risk=5, tax_rate=0.80, tax_collected=244, disaster_level=5),
    Region(name="中原", stability=60, garrison=15000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=55, rebellion_risk=20, tax_rate=0.50, tax_collected=66, disaster_level=15),
    Region(name="山东", stability=70, garrison=12000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=65, rebellion_risk=15, tax_rate=0.50, tax_collected=77, disaster_level=10),
    Region(name="云贵", stability=50, garrison=8000, threat=RegionThreat.TUSI, tax_contribution=TaxContribution.LOW,
           civil_morale=45, rebellion_risk=35, tax_rate=0.30, tax_collected=18, disaster_level=30),
    Region(name="川蜀", stability=65, garrison=10000, threat=RegionThreat.NONE, tax_contribution=TaxContribution.MEDIUM,
           civil_morale=60, rebellion_risk=15, tax_rate=0.50, tax_collected=71, disaster_level=10),
]

_MINISTERS_JSON = Path(__file__).resolve().parents[1] / "data" / "ministers.json"


def _load_initial_ministers() -> list[Minister]:
    raw = json.loads(_MINISTERS_JSON.read_text(encoding="utf-8"))
    ministers = [Minister.model_validate(item) for item in raw]
    names = [m.name for m in ministers]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate minister names in ministers.json")
    return ministers


INITIAL_MINISTERS = _load_initial_ministers()


def _time_key(year: int, month: int) -> int:
    return year * 12 + month


def create_initial_state() -> GameState:
    start_key = _time_key(1627, 8)
    ministers: list[Minister] = []
    for tpl in INITIAL_MINISTERS:
        m = tpl.model_copy()
        if m.status == MinisterStatus.ACTIVE and _time_key(m.entry_year, m.entry_month) > start_key:
            m.status = MinisterStatus.NOT_YET_ENTERED
        ministers.append(m)

    state = GameState(
        time=GameTime(year=1627, month=8, era_name="天启", era_year=7),
        national_treasury=20, imperial_treasury=10, grain=500,
        population=15000, military_strength=40,
        civil_morale=60, military_morale=70, court_prestige=75,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=ministers,
    )
    from engine.core import inject_script_events
    inject_script_events(state)
    return state


# ── Clamping ─────────────────────────────────────────────

def clamp_treasury(v: int | float) -> int:
    return max(0, min(10000, math.floor(v)))


def clamp_grain(v: int | float) -> int:
    return max(0, min(50000, math.floor(v)))


def clamp_population(v: int | float) -> int:
    return max(0, min(20000, math.floor(v)))


def clamp_military(v: int | float) -> int:
    return max(0, min(2000, math.floor(v)))


def clamp_indicator(v: int) -> int:
    return max(0, min(100, math.floor(v)))


def clamp_garrison(v: int) -> int:
    return max(0, math.floor(v))


def clamp_state(state: GameState) -> None:
    state.national_treasury = clamp_treasury(state.national_treasury)
    state.imperial_treasury = clamp_treasury(state.imperial_treasury)
    state.grain = clamp_grain(state.grain)
    state.population = clamp_population(state.population)
    state.military_strength = clamp_military(state.military_strength)
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
        m.loyalty = clamp_indicator(m.loyalty)
        m.abilities.civil = clamp_indicator(m.abilities.civil)
        m.abilities.military = clamp_indicator(m.abilities.military)
        m.abilities.diplomacy = clamp_indicator(m.abilities.diplomacy)


# ── Dialogue Models ─────────────────────────────────────

class DialogueRequest(BaseModel):
    message: str = Field(max_length=500)
    conversation_id: str | None = None


class DialogueResponse(BaseModel):
    reply: str
    loyalty_change: int = Field(ge=-3, le=3)
    mood: Literal["support", "neutral", "oppose"]
    conversation_id: str
    state: GameState
