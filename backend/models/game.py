from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from .enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    PersonnelAction, EventUrgency, MinisterStatus, MemorialStatus, AssemblyPhase,
)
from .positions import resolve_position
from .trpg import CharacterSheet, GrowthEntry
from .world import (
    Activity,
    CalendarProjection,
    EntityId,
    PlayerWorldStatus,
    WorldClock,
    WorldEntity,
    WorldSnapshotMetadata,
)
from .world_state import WorldStateLedger

MAX_MINISTER_CONVERSATION_MESSAGES = 50

DECREE_CATEGORY_MAP: dict[DecreeType, str] = {
    DecreeType.TAX_INCREASE: "domestic",
    DecreeType.TAX_DECREASE: "domestic",
    DecreeType.DISASTER_RELIEF: "domestic",
    DecreeType.HARSH_PUNISHMENT: "domestic",
    DecreeType.RECRUIT_TROOPS: "military",
    DecreeType.DISBAND_TROOPS: "military",
    DecreeType.DIPLOMACY: "diplomacy",
    DecreeType.PERSONNEL: "other",
}
VALID_DECREE_CATEGORIES = frozenset(DECREE_CATEGORY_MAP.values())
_CATEGORY_ALIASES = {
    "domestic": "domestic",
    "military": "military",
    "diplomacy": "diplomacy",
    "other": "other",
    "内政": "domestic",
    "军事": "military",
    "外交": "diplomacy",
    "其他": "other",
}


def decree_category_of(decree_type: DecreeType) -> str:
    return DECREE_CATEGORY_MAP[decree_type]


def normalize_decree_category_usage(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, bool] = {}
    for key, used in raw.items():
        if not used:
            continue
        if not isinstance(key, str):
            continue
        token = key.strip()
        if not token:
            continue

        mapped = _CATEGORY_ALIASES.get(token.lower(), _CATEGORY_ALIASES.get(token))
        if mapped in VALID_DECREE_CATEGORIES:
            normalized[mapped] = True
            continue

        try:
            decree_type = DecreeType(token)
        except ValueError:
            continue
        normalized[decree_category_of(decree_type)] = True

    return normalized


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
    administration: int = Field(default=50, ge=0, le=100)  # 管理（08-07-minister-agent）
    knowledge: int = Field(default=50, ge=0, le=100)        # 知识
    politics: int = Field(default=50, ge=0, le=100)         # 政治


class MissionState(BaseModel):
    name: str
    progress_months: int = 0
    total_months: int = Field(ge=2, le=12)
    cost: int = Field(ge=0)
    effects: dict = Field(default_factory=dict)


class PolicyProgress(BaseModel):
    """国家层面的长期在办国策（区别于大臣任务 MissionState），随存档持久化。"""
    name: str
    started_year: int
    started_month: int
    summary: str = ""
    effects: dict = Field(default_factory=dict)


class Minister(BaseModel):
    name: str
    faction: str
    personality_tags: list[str] = Field(default_factory=list, max_length=4)
    abilities: MinisterAbilities = Field(default_factory=MinisterAbilities)
    status: MinisterStatus = MinisterStatus.ACTIVE
    loyalty: int = Field(default=50, ge=0, le=100)
    corruption: int = Field(default=10, ge=0, le=100)
    ambition: int = Field(default=30, ge=0, le=100)   # 野心（08-07-minister-agent）
    influence: int = Field(default=30, ge=0, le=100)  # 势力（个人）
    positions: list[str] = Field(default_factory=list)
    is_eunuch: bool = False
    entry_year: int = 1356
    entry_month: int = Field(default=3, ge=1, le=12)
    historical_note: str = Field(default="", max_length=200)
    biography: str = Field(default="")
    major_contributions: list[str] = Field(default_factory=list)
    current_mission: MissionState | None = None


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
    resolution_result: MemorialResolutionResult | None = None


class MinisterReaction(BaseModel):
    minister_name: str
    faction: str
    reaction_type: str
    reaction_text: str
    loyalty_change: int


class MemorialResolutionResult(BaseModel):
    action: Literal['approved', 'rejected', 'deferred']
    narrative: str | None = None
    delta: dict[str, float] | None = None
    minister_reactions: list[MinisterReaction] | None = None


class FreeformResult(BaseModel):
    effects: dict[str, int | float | str | dict] = Field(default_factory=dict)
    narrative: str = ""
    reactions: list[MinisterReaction] = Field(default_factory=list)
    rationale: str = ""
    new_events: list["GameEvent"] = Field(default_factory=list)


# ── Court Assembly ──────────────────────────────────────

class AssemblyParticipant(BaseModel):
    name: str
    faction: str
    position: str
    argument_text: str
    entity_id: EntityId | None = None
    entity_type: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    capability_sources: list[str] = Field(default_factory=list)


class SuggestionRationaleFactor(BaseModel):
    """Safe, current-world evidence for a player-visible policy suggestion."""

    fact_reference: str = Field(min_length=1, max_length=240)
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)


class PolicySuggestion(BaseModel):
    title: str
    description: str
    related_decree: StructuredDecree
    supporter_names: list[str] = Field(default_factory=list)
    suggestion_id: str | None = Field(default=None, max_length=64)
    source_game_id: UUID | None = None
    source_branch_id: UUID | None = None
    source_version_id: UUID | None = None
    rationale_factors: list[SuggestionRationaleFactor] = Field(default_factory=list)


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
    narrative_status: Literal[
        "validated", "repaired", "sanitized", "fallback_facts",
    ] | None = None
    narrative_path_id: str | None = None
    settlement_id: UUID | None = None
    context_version_id: UUID | None = None
    narrative_artifact_id: UUID | None = None
    narrative_request_id: str | None = None
    narrative_progress: list[str] = Field(default_factory=list)


# ── Event ────────────────────────────────────────────────

class EventChoice(BaseModel):
    label: str
    description: str = ""
    decrees: list[StructuredDecree] = Field(default_factory=list)
    loyalty_effects: list[tuple[str, int]] = Field(default_factory=list)
    # int = 数值增量；str = 枚举字段直设（region.*.threat/control，史实威胁清除）
    state_effects: dict[str, int | str] = Field(default_factory=dict)


class GameEvent(BaseModel):
    name: str
    description: str = ""
    urgency: EventUrgency = EventUrgency.LOW
    triggered_year: int = 0
    triggered_month: int = 1
    rich_description: str = ""
    choices: list[EventChoice] = Field(default_factory=list)
    is_scripted: bool = False
    is_blocking: bool = False
    script_id: str | None = None
    historical_hint: str = ""
    historical_basis: str = ""


# ── Script Trigger Decision ──────────────────────────────

class TriggerDecision(BaseModel):
    should_trigger: bool
    reason: str = ""
    timestamp: str = ""


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
    year: int = 1356
    month: int = 3
    era_name: str = "至正"
    era_year: int = 16
    clock: WorldClock | None = None
    calendar: CalendarProjection | None = None
    time_migration_source: Literal["initial_world", "legacy_year_month"] | None = None


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
    # Additive world-version foundation. Legacy gameplay continues to use the
    # lists below until its route is migrated; committed world snapshots carry
    # their durable identity here and can be reloaded without process state.
    world_metadata: WorldSnapshotMetadata = Field(default_factory=WorldSnapshotMetadata)
    entity_registry: dict[EntityId, WorldEntity] = Field(default_factory=dict)
    player_world_status: PlayerWorldStatus = Field(default_factory=PlayerWorldStatus)
    activities: list[Activity] = Field(default_factory=list)
    world_state: WorldStateLedger = Field(default_factory=WorldStateLedger)
    # phase state machine (阶段切换逻辑属阶段D)
    # 阶段B：默认翻转为 life_story（跑团叙事开局）；治理开局档由存档迁移保留 governance
    phase: Literal["life_story", "governance"] = "life_story"
    # 人生篇章（阶段B：childhood/monk_wanderer/enlistment/warlord，推进逻辑见 trpg/chapter.py）
    chapter: str = "childhood"
    chapter_turns: int = Field(default=0, ge=0)
    # resources (historical scales)
    national_treasury: int = Field(default=15, ge=0, le=10000)
    imperial_treasury: int = Field(default=8, ge=0, le=10000)
    grain: int = Field(default=420, ge=0, le=50000)
    population: int = Field(default=1600, ge=0, le=20000)
    military_strength: int = Field(default=18, ge=0, le=2000)
    # indicators (0~100)
    civil_morale: int = 62
    military_morale: int = 68
    court_prestige: int = 62
    # entities
    factions: list[Faction] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    ministers: list[Minister] = Field(default_factory=list)
    active_events: list[GameEvent] = Field(default_factory=list)
    history_log: list[HistoryEntry] = Field(default_factory=list)
    decree_count: int = 0
    # category-keyed usage map: domestic/military/diplomacy/other
    decrees_this_month: dict[str, bool] = Field(default_factory=dict)
    event_cooldowns: dict[str, int] = Field(default_factory=dict)
    resolved_script_ids: set[str] = Field(default_factory=set)
    trigger_decisions: dict[str, TriggerDecision] = Field(default_factory=dict)
    memorials: list[Memorial] = Field(default_factory=list)
    memorial_cooldowns: dict[str, int] = Field(default_factory=dict)
    last_assembly: CourtAssembly | None = None
    loyalty_zero_triggered: set[str] = Field(default_factory=set)
    last_assembly_month: int = 0
    consecutive_waits: int = 0
    minister_conversations: dict[str, list[ConversationMessage]] = Field(default_factory=dict)
    # ── TRPG（阶段B）：角色卡与成长记录，随存档持久化 ──
    character_sheets: dict[str, CharacterSheet] = Field(default_factory=dict)
    growth_log: list[GrowthEntry] = Field(default_factory=list)
    # Legacy-compatible deterministic seed; ordinary actions never use hidden deviation.
    execution_rng_seed: int | None = None
    # 在办国策（国家层面长期政令，区别于大臣任务），随存档持久化
    active_policies: list[PolicyProgress] = Field(default_factory=list)

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

    @field_validator("decrees_this_month", mode="before")
    @classmethod
    def _normalize_decrees_this_month(cls, value):
        return normalize_decree_category_usage(value)

    @field_validator("trigger_decisions", mode="before")
    @classmethod
    def _normalize_trigger_decisions(cls, value):
        if value is None or not isinstance(value, dict):
            return {}
        return value

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
    narrative_status: Literal[
        "validated", "repaired", "sanitized", "fallback_facts",
    ] | None = None
    narrative_path_id: str | None = None
    settlement_id: UUID | None = None
    context_version_id: UUID | None = None
    narrative_artifact_id: UUID | None = None
    narrative_request_id: str | None = None
    narrative_progress: list[str] = Field(default_factory=list)


# ── Error ────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict[str, Any] | None = None
    fix_hint: str | None = None
    request_id: str | None = None
    provider_summary: str | None = None
    retryable: bool | None = None


# ── Factory ──────────────────────────────────────────────

_YUANMING_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "yuanming"
_FACTIONS_JSON = _YUANMING_DATA_DIR / "factions.json"
_REGIONS_JSON = _YUANMING_DATA_DIR / "regions.json"


def _load_initial_factions() -> list[Faction]:
    raw = json.loads(_FACTIONS_JSON.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("factions.json must be a JSON array")
    factions = [
        Faction(
            name=item["name"],
            satisfaction=item["satisfaction"],
            influence=item["influence"],
            rebellion_risk=item["rebellion_risk"],
        )
        for item in raw
    ]
    names = [f.name for f in factions]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate faction names in factions.json")
    return factions


def _load_initial_regions() -> list[Region]:
    raw = json.loads(_REGIONS_JSON.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("regions.json must be a JSON array")
    regions = [Region.model_validate(item) for item in raw]
    names = [r.name for r in regions]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate region names in regions.json")
    return regions


INITIAL_FACTIONS = _load_initial_factions()

INITIAL_REGIONS = _load_initial_regions()

_MINISTERS_JSON = _YUANMING_DATA_DIR / "ministers.json"
_INITIAL_MINISTERS_CACHE: list[Minister] | None = None
_INITIAL_MINISTERS_SIGNATURE: int | None = None
_INITIAL_MINISTERS_LOCK = threading.RLock()


def _try_get_data_manager():
    try:
        from data.data_manager import get_data_manager
    except Exception:
        return None
    return get_data_manager()


def _split_position_text(value: str) -> list[str]:
    tokens = [value]
    for delimiter in ("兼", "、", "，", ","):
        next_tokens: list[str] = []
        for token in tokens:
            next_tokens.extend(token.split(delimiter))
        tokens = next_tokens
    return [token.strip() for token in tokens if token.strip()]


def _normalize_positions(item: dict) -> list[str]:
    raw_positions = item.get("positions")
    if raw_positions is None:
        legacy_position = str(item.get("position", "")).strip()
        raw_positions = _split_position_text(legacy_position) if legacy_position else []

    if isinstance(raw_positions, str):
        raw_positions = [raw_positions]

    if not isinstance(raw_positions, list):
        raise ValueError(
            f"Invalid positions format for minister {item.get('name', '<unknown>')}: {raw_positions!r}"
        )

    normalized_positions: list[str] = []
    for raw_position in raw_positions:
        if not isinstance(raw_position, str):
            raise ValueError(
                f"Invalid position value for minister {item.get('name', '<unknown>')}: {raw_position!r}"
            )
        for token in _split_position_text(raw_position):
            canonical = resolve_position(token)
            if canonical is None:
                raise ValueError(
                    f"Invalid position '{token}' for minister {item.get('name', '<unknown>')}"
                )
            if canonical not in normalized_positions:
                normalized_positions.append(canonical)
    return normalized_positions


def _read_initial_ministers_file() -> list[Minister]:
    manager = _try_get_data_manager()
    if manager is not None:
        raw = manager.get_ministers()
    else:
        raw = json.loads(_MINISTERS_JSON.read_text(encoding="utf-8"))

    normalized_raw: list[dict] = []
    for item in raw:
        normalized_item = dict(item)

        normalized_item["positions"] = _normalize_positions(item)
        normalized_item["is_eunuch"] = bool(item.get("is_eunuch", False))
        normalized_raw.append(normalized_item)
    ministers = [Minister.model_validate(item) for item in normalized_raw]
    names = [m.name for m in ministers]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate minister names in ministers.json")
    return ministers


def get_initial_ministers(*, refresh: bool = False) -> list[Minister]:
    global _INITIAL_MINISTERS_CACHE
    global _INITIAL_MINISTERS_SIGNATURE

    with _INITIAL_MINISTERS_LOCK:
        manager = _try_get_data_manager()
        if manager is not None:
            ministers_mtime_ns = manager.ministers_path.stat().st_mtime_ns
        else:
            ministers_mtime_ns = _MINISTERS_JSON.stat().st_mtime_ns
        signature = ministers_mtime_ns

        if refresh or _INITIAL_MINISTERS_CACHE is None or signature != _INITIAL_MINISTERS_SIGNATURE:
            _INITIAL_MINISTERS_CACHE = _read_initial_ministers_file()
            _INITIAL_MINISTERS_SIGNATURE = signature
        return [minister.model_copy(deep=True) for minister in _INITIAL_MINISTERS_CACHE]


INITIAL_MINISTERS = get_initial_ministers(refresh=True)


def _time_key(year: int, month: int) -> int:
    return year * 12 + month


def create_initial_state() -> GameState:
    # 跑团开局时间锚点：1328-10（出生月，与 birth-1328 里程碑一致；阶段D 时间轴对齐）
    from engine.calendar import set_game_time_projection
    from engine.core import LIFE_STORY_START_MONTH, LIFE_STORY_START_YEAR
    start_key = _time_key(LIFE_STORY_START_YEAR, LIFE_STORY_START_MONTH)
    ministers: list[Minister] = []
    for tpl in get_initial_ministers():
        m = tpl.model_copy()
        if m.status == MinisterStatus.ACTIVE and _time_key(m.entry_year, m.entry_month) > start_key:
            m.status = MinisterStatus.NOT_YET_ENTERED
        elif m.status == MinisterStatus.ACTIVE:
            m.status = MinisterStatus.ACTIVE if m.positions else MinisterStatus.IDLE
        ministers.append(m)

    initial_time = GameTime(year=LIFE_STORY_START_YEAR, month=LIFE_STORY_START_MONTH)
    set_game_time_projection(
        initial_time,
        year=LIFE_STORY_START_YEAR,
        month=LIFE_STORY_START_MONTH,
        migration_source="initial_world",
    )
    state = GameState(
        time=initial_time,
        national_treasury=15, imperial_treasury=8, grain=420,
        population=1600, military_strength=18,
        civil_morale=62, military_morale=68, court_prestige=62,
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
        m.corruption = clamp_indicator(m.corruption)
        m.ambition = clamp_indicator(m.ambition)
        m.influence = clamp_indicator(m.influence)
        m.abilities.civil = clamp_indicator(m.abilities.civil)
        m.abilities.military = clamp_indicator(m.abilities.military)
        m.abilities.diplomacy = clamp_indicator(m.abilities.diplomacy)
        m.abilities.administration = clamp_indicator(m.abilities.administration)
        m.abilities.knowledge = clamp_indicator(m.abilities.knowledge)
        m.abilities.politics = clamp_indicator(m.abilities.politics)


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
    narrative_status: Literal[
        "validated", "repaired", "sanitized", "fallback_facts",
    ]
    narrative_path_id: str
    settlement_id: UUID
    context_version_id: UUID
    narrative_artifact_id: UUID | None = None
    narrative_request_id: str
    narrative_progress: list[str] = Field(default_factory=list)
