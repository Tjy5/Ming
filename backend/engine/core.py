from __future__ import annotations

import logging
import math
import os
import uuid

from models.game import (
    GameState, StructuredDecree, DecreeResponse, GameTime,
    GameEvent, HistoryEntry, MinisterReaction, Memorial,
    TurnSummary, IndicatorTrend, FactionChange, RegionChange, MinisterChange,
    RegionDetail,
    FreeformResult, MissionState,
    clamp_state,
)
from models.enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    EventUrgency, MinisterStatus, PersonnelAction, MemorialStatus,
)
from .tables import (
    DECREE_EFFECTS, FACTION_STANCE, DECREE_PRECONDITIONS,
    DECREE_TARGET_REQUIRED, REGION_NAMES, DIPLOMACY_TARGETS,
    PRECONDITION_MESSAGES, TARGET_MISSING_MESSAGES,
    WRITABLE_FIELDS, VALID_STATUS_TRANSITIONS,
    DECREE_LABELS,
    CONSECUTIVE_WAIT_THRESHOLD, WAIT_PRESTIGE_PENALTY, WAIT_MORALE_PENALTY,
    PENDING_MEMORIAL_THRESHOLD, PENDING_MEMORIAL_PRESTIGE_PENALTY,
    APPOINT_LOYALTY_BONUS, DISMISS_LOYALTY_PENALTY,
    EXECUTION_SATISFACTION_PENALTY, EXECUTION_REBELLION_RISK,
)
from .scripts import get_scripts_for_time, ScriptEvent

logger = logging.getLogger(__name__)

_LOCK_TIMEOUT_DEFAULT_SECONDS = 5
_LOCK_TIMEOUT_MIN_SECONDS = 1
_LOCK_TIMEOUT_MAX_SECONDS = 30
_MONTHLY_LIMITED = {"tax_increase", "tax_decrease", "recruit_troops", "disband_troops", "harsh_punishment", "disaster_relief", "diplomacy"}


def _parse_lock_timeout_seconds(raw: str | None) -> int:
    if raw is None:
        return _LOCK_TIMEOUT_DEFAULT_SECONDS
    value = raw.strip()
    if not value:
        return _LOCK_TIMEOUT_DEFAULT_SECONDS
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _LOCK_TIMEOUT_DEFAULT_SECONDS
    if not (_LOCK_TIMEOUT_MIN_SECONDS <= parsed <= _LOCK_TIMEOUT_MAX_SECONDS):
        return _LOCK_TIMEOUT_DEFAULT_SECONDS
    return parsed


LOCK_TIMEOUT_SECONDS = _parse_lock_timeout_seconds(
    os.getenv("LOCK_TIMEOUT_SECONDS"),
)


# ── Era Config ──────────────────────────────────────────

ERA_CONFIG = [
    {"name": "天启", "start_year": 1621},
    {"name": "崇祯", "start_year": 1628},
]


def resolve_era(year: int) -> tuple[str, int]:
    era = ERA_CONFIG[0]
    for e in ERA_CONFIG:
        if e["start_year"] <= year:
            era = e
        else:
            break
    return era["name"], year - era["start_year"] + 1


# ── Attribution helper ───────────────────────────────────

def _attr_add(attr: dict, key: str, source: str, value: int | float) -> None:
    if value == 0:
        return
    attr.setdefault(key, {})[source] = attr.get(key, {}).get(source, 0) + value


# ── Validation ───────────────────────────────────────────

def check_preconditions(state: GameState, decree: StructuredDecree) -> str | None:
    conditions = DECREE_PRECONDITIONS.get(decree.type, [])
    for field, op, threshold in conditions:
        val = getattr(state, field)
        ok = (val > threshold) if op == ">" else (val >= threshold)
        if not ok:
            tpl = PRECONDITION_MESSAGES.get(decree.type, "前置条件不满足")
            return tpl.format(**{
                "national_treasury": state.national_treasury, "imperial_treasury": state.imperial_treasury,
                "grain": state.grain, "population": state.population,
                "military_strength": state.military_strength, "civil_morale": state.civil_morale,
                "military_morale": state.military_morale, "court_prestige": state.court_prestige,
                # backward-compatible placeholders for legacy templates
                "treasury": state.national_treasury,
                "military_supply": state.military_strength,
            })
    if decree.type.value in _MONTHLY_LIMITED and decree.type.value in state.decrees_this_month:
        return "本月已下达此类政令"
    return None


def _minister_exists(state: GameState, name: str) -> bool:
    return any(m.name == name for m in state.ministers)


def validate_target(decree: StructuredDecree, state: GameState | None = None) -> str | None:
    req = DECREE_TARGET_REQUIRED.get(decree.type)
    if req is None:
        return None
    if req == "region":
        if not decree.target or decree.target not in REGION_NAMES:
            return TARGET_MISSING_MESSAGES[decree.type]
    elif req == "person":
        if not decree.target or not decree.sub_action:
            return TARGET_MISSING_MESSAGES[decree.type]
        if state is not None:
            target = next((m for m in state.ministers if m.name == decree.target), None)
            if target is None:
                return "任免目标人物不存在"
            if target.status == MinisterStatus.NOT_YET_ENTERED:
                return "该人物尚未入朝，当前不可任免"
    elif req == "diplomacy_target":
        if not decree.target or decree.target not in DIPLOMACY_TARGETS:
            return TARGET_MISSING_MESSAGES[decree.type]
    return None


# ── Minister Status Transition ──────────────────────────

def apply_minister_transition(state: GameState, decree: StructuredDecree) -> tuple[set[str], set[str]]:
    """Returns (dismissed, executed) sets of minister names changed this turn."""
    dismissed: set[str] = set()
    executed: set[str] = set()
    if decree.type != DecreeType.PERSONNEL or not decree.target or not decree.sub_action:
        return dismissed, executed
    for m in state.ministers:
        if m.name == decree.target:
            if decree.sub_action == PersonnelAction.DISMISS and m.status == MinisterStatus.ACTIVE:
                m.status = MinisterStatus.IDLE
                dismissed.add(m.name)
            elif decree.sub_action == PersonnelAction.EXECUTE and m.status in {MinisterStatus.ACTIVE, MinisterStatus.IDLE}:
                m.status = MinisterStatus.REMOVED
                executed.add(m.name)
            elif decree.sub_action == PersonnelAction.APPOINT and m.status == MinisterStatus.IDLE:
                pos = decree.parameters.get("position", "") if decree.parameters else ""
                if not pos:
                    break
                m.status = MinisterStatus.ACTIVE
                for other in state.ministers:
                    if other.name != m.name and other.status == MinisterStatus.ACTIVE and other.position == pos:
                        other.position = ""
                m.position = pos
            break
    return dismissed, executed


# ── Passive Drift ────────────────────────────────────────

def apply_passive_drift(state: GameState, attr: dict) -> None:
    """Apply per-turn passive world drift.

    This models maintenance costs, region self-evolution under threats/disasters,
    baseline loyalty decay, and penalties from unattended memorial workload.
    All numeric changes are recorded into ``attr`` for narrative/summary attribution.
    """
    # unconditional administrative & grain & military upkeep
    state.national_treasury -= 1
    state.grain -= 6
    state.military_strength -= 1
    _attr_add(attr, "national_treasury", "自然变化", -1)
    _attr_add(attr, "grain", "自然变化", -6)
    _attr_add(attr, "military_strength", "自然变化", -1)

    for r in state.regions:
        if r.threat != RegionThreat.NONE:
            r.stability -= 2
            r.civil_morale -= 1
            r.disaster_level += 2
            _attr_add(attr, f"{r.name}_stability", "自然变化", -2)
            _attr_add(attr, f"{r.name}_civil_morale", "自然变化", -1)
            _attr_add(attr, f"{r.name}_disaster_level", "自然变化", 2)
        elif r.disaster_level > 20:
            r.stability -= 1
            r.civil_morale -= 1
            _attr_add(attr, f"{r.name}_stability", "自然变化", -1)
            _attr_add(attr, f"{r.name}_civil_morale", "自然变化", -1)
        if r.stability < 30:
            r.rebellion_risk += 2
            r.tax_rate -= 0.02
            _attr_add(attr, f"{r.name}_rebellion_risk", "自然变化", 2)
            _attr_add(attr, f"{r.name}_tax_rate", "自然变化", -0.02)
        if r.civil_morale < 30:
            r.rebellion_risk += 1
            _attr_add(attr, f"{r.name}_rebellion_risk", "自然变化", 1)
    if state.national_treasury < 10 or state.grain < 200:
        state.military_morale -= 1
        _attr_add(attr, "military_morale", "自然变化", -1)
    if any(r.stability < 20 for r in state.regions):
        state.civil_morale -= 2
        _attr_add(attr, "civil_morale", "自然变化", -2)
    if any(f.rebellion_risk > 60 for f in state.factions):
        state.court_prestige -= 1
        _attr_add(attr, "court_prestige", "自然变化", -1)
    # loyalty passive decay
    for m in state.ministers:
        if m.status == MinisterStatus.NOT_YET_ENTERED:
            continue
        m.loyalty -= 1
        _attr_add(attr, f"{m.name}_loyalty", "自然变化", -1)
    # military strength: stable garrisoned regions provide trained manpower
    supply_prod = sum(
        1 for r in state.regions
        if r.stability >= 50 and r.garrison >= 10000
        and r.control == RegionControl.COURT
    )
    if supply_prod > 0:
        gain = min(supply_prod, 3)
        state.military_strength += gain
        _attr_add(attr, "military_strength", "军备生产", gain)
    # 怠政惩罚: pending/deferred memorials > 5
    pending_count = sum(
        1 for mem in state.memorials
        if mem.status in {MemorialStatus.PENDING, MemorialStatus.DEFERRED}
    )
    if pending_count > PENDING_MEMORIAL_THRESHOLD:
        state.court_prestige -= PENDING_MEMORIAL_PRESTIGE_PENALTY
        _attr_add(attr, "court_prestige", "自然变化", -PENDING_MEMORIAL_PRESTIGE_PENALTY)


# ── Base Effects ─────────────────────────────────────────

def apply_base_effects(state: GameState, decree: StructuredDecree, attr: dict) -> None:
    """Apply direct decree effect table deltas to global state fields."""
    effects = DECREE_EFFECTS[decree.type]
    for field, delta in effects.items():
        if delta == 0:
            continue
        setattr(state, field, getattr(state, field) + delta)
        _attr_add(attr, field, "base_effect", delta)


# ── Faction Reactions ────────────────────────────────────

def apply_faction_reactions(state: GameState, decree: StructuredDecree, attr: dict) -> None:
    """Apply faction satisfaction/risk shifts driven by decree stance and influence."""
    for faction in state.factions:
        stance = FACTION_STANCE.get(faction.name, {})
        modifier = stance.get(decree.type, 0)
        if modifier == 0:
            continue
        sat_change = math.floor(modifier * faction.influence / 100)
        # low loyalty discount: min active loyalty < 30 → scale positive effect
        if sat_change > 0:
            active_loyalties = [
                m.loyalty for m in state.ministers
                if m.status == MinisterStatus.ACTIVE and m.faction == faction.name
            ]
            if active_loyalties:
                min_loyalty = max(0, min(active_loyalties))
                if min_loyalty < 30:
                    sat_change = math.floor(sat_change * min_loyalty / 50)
        faction.satisfaction += sat_change
        _attr_add(attr, f"{faction.name}_satisfaction", "faction_reaction", sat_change)
        if sat_change < 0:
            risk_change = math.floor(abs(sat_change) * 0.3)
            faction.rebellion_risk += risk_change
            _attr_add(attr, f"{faction.name}_rebellion_risk", "faction_reaction", risk_change)
        elif sat_change > 0:
            risk_change = math.floor(sat_change * 0.2)
            faction.rebellion_risk -= risk_change
            _attr_add(attr, f"{faction.name}_rebellion_risk", "faction_reaction", -risk_change)


# ── Loyalty Modification ────────────────────────────────

def apply_loyalty_modification(
    state: GameState, decree: StructuredDecree, attr: dict,
    dismissed: set[str] | None = None,
) -> None:
    for m in state.ministers:
        if m.status != MinisterStatus.ACTIVE:
            # only apply dismiss -20 if actually dismissed this turn
            if dismissed and m.name in dismissed:
                m.loyalty -= DISMISS_LOYALTY_PENALTY
                _attr_add(attr, f"{m.name}_loyalty", "loyalty_modification", -DISMISS_LOYALTY_PENALTY)
            continue
        stance = FACTION_STANCE.get(m.faction, {}).get(decree.type, 0)
        delta = 0
        if stance > 0:
            delta += math.floor(stance * 0.3)
        elif stance < 0:
            delta += math.floor(stance * 0.5)
        # personnel special: appoint +15, dismiss -20
        if decree.type == DecreeType.PERSONNEL and decree.target == m.name:
            if decree.sub_action == PersonnelAction.APPOINT:
                delta += APPOINT_LOYALTY_BONUS
            elif decree.sub_action == PersonnelAction.DISMISS:
                delta -= DISMISS_LOYALTY_PENALTY
        if delta == 0:
            continue
        m.loyalty += delta
        _attr_add(attr, f"{m.name}_loyalty", "loyalty_modification", delta)


# ── Minister Reactions ──────────────────────────────────

def generate_minister_reactions(
    state: GameState, decree: StructuredDecree, attr: dict,
) -> list[MinisterReaction]:
    supporters: list[tuple[int, int, object]] = []  # (stance, idx, minister)
    opposers: list[tuple[int, int, object]] = []
    for idx, m in enumerate(state.ministers):
        if m.status != MinisterStatus.ACTIVE:
            continue
        stance = FACTION_STANCE.get(m.faction, {}).get(decree.type, 0)
        if stance > 5:
            supporters.append((stance, idx, m))
        elif stance < -5:
            opposers.append((stance, idx, m))
    supporters.sort(key=lambda x: (-x[0], x[1]))
    opposers.sort(key=lambda x: (x[0], x[1]))
    reactions: list[MinisterReaction] = []
    for stance_val, _, minister in (supporters[:2] + opposers[:2]):
        loyalty_delta = int(
            attr.get(f"{minister.name}_loyalty", {}).get("loyalty_modification", 0)
        )
        if stance_val > 0:
            rtype = "support"
            rtext = f"{minister.name}拱手道：陛下圣明。"
        else:
            rtype = "oppose"
            rtext = f"{minister.name}跪奏：臣以为此举不妥，恳请陛下三思。"
        reactions.append(MinisterReaction(
            minister_name=minister.name,
            faction=minister.faction,
            reaction_type=rtype,
            reaction_text=rtext,
            loyalty_change=loyalty_delta,
        ))
    return reactions


# ── Region Impact ────────────────────────────────────────

def apply_region_impact(state: GameState, decree: StructuredDecree, attr: dict) -> float:
    """Returns decree_tax_modifier for tax recalculation."""
    dt = decree.type
    tax_mod = 1.0
    source = DECREE_LABELS.get(dt, "政令")
    for r in state.regions:
        if dt == DecreeType.TAX_INCREASE:
            if r.stability < 30:
                penalty = -8
            elif r.stability < 60:
                penalty = -5
            else:
                penalty = -3
            r.stability += penalty
            r.civil_morale -= 2
            r.rebellion_risk += 1
            _attr_add(attr, f"{r.name}_stability", source, penalty)
            _attr_add(attr, f"{r.name}_civil_morale", source, -2)
            _attr_add(attr, f"{r.name}_rebellion_risk", source, 1)
            tax_mod = 1.20
        elif dt == DecreeType.TAX_DECREASE:
            r.stability += 3
            r.civil_morale += 2
            r.rebellion_risk -= 1
            _attr_add(attr, f"{r.name}_stability", source, 3)
            _attr_add(attr, f"{r.name}_civil_morale", source, 2)
            _attr_add(attr, f"{r.name}_rebellion_risk", source, -1)
            tax_mod = 0.85
        elif dt == DecreeType.RECRUIT_TROOPS:
            if r.threat != RegionThreat.NONE:
                r.stability += 5
                r.garrison += 2000
                r.civil_morale -= 2
                _attr_add(attr, f"{r.name}_stability", source, 5)
                _attr_add(attr, f"{r.name}_garrison", source, 2000)
                _attr_add(attr, f"{r.name}_civil_morale", source, -2)
        elif dt == DecreeType.DISBAND_TROOPS:
            if r.garrison > 10000:
                r.garrison -= 3000
                _attr_add(attr, f"{r.name}_garrison", source, -3000)
        elif dt == DecreeType.DISASTER_RELIEF:
            if decree.target and r.name == decree.target:
                r.stability += 22
                r.civil_morale += 10
                r.disaster_level -= 18
                r.rebellion_risk -= 8
                _attr_add(attr, f"{r.name}_stability", source, 22)
                _attr_add(attr, f"{r.name}_civil_morale", source, 10)
                _attr_add(attr, f"{r.name}_disaster_level", source, -18)
                _attr_add(attr, f"{r.name}_rebellion_risk", source, -8)
        elif dt == DecreeType.HARSH_PUNISHMENT:
            if r.stability < 40:
                r.stability -= 8
                r.rebellion_risk -= 5
                _attr_add(attr, f"{r.name}_stability", source, -8)
                _attr_add(attr, f"{r.name}_rebellion_risk", source, -5)
            elif r.stability >= 60:
                r.stability += 3
                _attr_add(attr, f"{r.name}_stability", source, 3)
            r.civil_morale -= 4
            _attr_add(attr, f"{r.name}_civil_morale", source, -4)
    return tax_mod


# ── Region Control State Machine ─────────────────────────

def update_region_control(state: GameState) -> None:
    for r in state.regions:
        if r.control == RegionControl.COURT and r.stability < 15:
            r.control = RegionControl.UNSTABLE
        elif r.control == RegionControl.UNSTABLE and r.stability <= 5:
            r.control = RegionControl.FALLEN
        elif r.control == RegionControl.UNSTABLE and r.stability > 35 and r.rebellion_risk < 60:
            r.control = RegionControl.COURT
        elif r.control == RegionControl.FALLEN and r.stability >= 25 and r.rebellion_risk <= 70:
            r.control = RegionControl.UNSTABLE


def apply_region_control_consequences(state: GameState, attr: dict) -> None:
    """Fallen/unstable regions bleed national resources each turn."""
    fallen = sum(1 for r in state.regions if r.control == RegionControl.FALLEN)
    unstable = sum(1 for r in state.regions if r.control == RegionControl.UNSTABLE)
    if fallen == 0 and unstable == 0:
        return
    treasury_loss = fallen * 3 + unstable
    civil_loss = fallen
    military_loss = max(0, fallen - 1)
    prestige_loss = fallen * 2 + (1 if unstable > 2 else 0)
    state.national_treasury -= treasury_loss
    state.civil_morale -= civil_loss
    state.military_morale -= military_loss
    state.court_prestige -= prestige_loss
    _attr_add(attr, "national_treasury", "疆域失控", -treasury_loss)
    _attr_add(attr, "civil_morale", "疆域失控", -civil_loss)
    _attr_add(attr, "military_morale", "疆域失控", -military_loss)
    _attr_add(attr, "court_prestige", "疆域失控", -prestige_loss)


# ── Chain Events ─────────────────────────────────────────

CHAIN_EVENTS = [
    {
        "name": "流寇势力扩大",
        "check": lambda s: _region(s, "陕西").stability < 20 and s.civil_morale < 40,
        "apply": lambda s, a: _chain_apply(s, a, "流寇势力扩大", [
            ("陕西", "stability", -5), ("中原", "stability", -10),
            ("陕西", "rebellion_risk", 10), ("中原", "rebellion_risk", 5),
            ("陕西", "disaster_level", 10),
        ]),
    },
    {
        "name": "边军哗变",
        "check": lambda s: s.military_morale < 25 and s.national_treasury < 8,
        "apply": lambda s, a: _chain_apply(s, a, "边军哗变", [
            ("辽东", "stability", -20), ("辽东", "rebellion_risk", 15),
        ], faction_effects=[("辽东边将", "rebellion_risk", 25)]),
    },
    {
        "name": "朝堂危机",
        "check": lambda s: any(f.rebellion_risk > 80 for f in s.factions) and s.court_prestige < 30,
        "apply": lambda s, a: _chain_crisis(s, a),
    },
    {
        "name": "江南税变",
        "check": lambda s: s.national_treasury < 5 and _region(s, "江南").stability > 50,
        "apply": lambda s, a: _chain_jiangnan(s, a),
    },
    {
        "name": "后金入寇",
        "check": lambda s: _region(s, "辽东").stability < 15 and s.military_strength < 15,
        "apply": lambda s, a: _chain_apply(s, a, "后金入寇", [
            ("辽东", "stability", -20), ("京畿", "stability", -10),
            ("辽东", "disaster_level", 20), ("京畿", "disaster_level", 10),
        ], global_effects=[("military_morale", -15)]),
    },
]


def _region(state: GameState, name: str, *, context: str = "_region"):
    region = next((r for r in state.regions if r.name == name), None)
    if region is None:
        logger.warning(
            "Entity not found",
            extra={
                "entity_type": "region",
                "entity_name": name,
                "context": context,
            },
        )
    return region


def _faction(state: GameState, name: str, *, context: str = "_faction"):
    faction = next((fc for fc in state.factions if fc.name == name), None)
    if faction is None:
        logger.warning(
            "Entity not found",
            extra={
                "entity_type": "faction",
                "entity_name": name,
                "context": context,
            },
        )
    return faction


def _minister(state: GameState, name: str, *, context: str = "_minister"):
    minister = next((m for m in state.ministers if m.name == name), None)
    if minister is None:
        logger.warning(
            "Entity not found",
            extra={
                "entity_type": "minister",
                "entity_name": name,
                "context": context,
            },
        )
    return minister


def _chain_apply(state, attr, event_name, region_effects, faction_effects=None, global_effects=None):
    context = f"_chain_apply:{event_name}"
    for rname, field, delta in region_effects:
        r = _region(state, rname, context=context)
        if r is None:
            continue
        if not hasattr(r, field):
            logger.warning(
                "Entity field not found",
                extra={
                    "entity_type": "region",
                    "entity_name": f"{rname}.{field}",
                    "context": context,
                },
            )
            continue
        setattr(r, field, getattr(r, field) + delta)
        _attr_add(attr, f"{rname}_{field}", event_name, delta)
    for fname, field, delta in (faction_effects or []):
        f = _faction(state, fname, context=context)
        if f is None:
            continue
        if not hasattr(f, field):
            logger.warning(
                "Entity field not found",
                extra={
                    "entity_type": "faction",
                    "entity_name": f"{fname}.{field}",
                    "context": context,
                },
            )
            continue
        setattr(f, field, getattr(f, field) + delta)
        _attr_add(attr, f"{fname}_{field}", event_name, delta)
    for field, delta in (global_effects or []):
        if not hasattr(state, field):
            logger.warning(
                "Entity field not found",
                extra={
                    "entity_type": "global",
                    "entity_name": field,
                    "context": context,
                },
            )
            continue
        setattr(state, field, getattr(state, field) + delta)
        _attr_add(attr, field, event_name, delta)


def _chain_crisis(state, attr):
    state.court_prestige -= 15
    _attr_add(attr, "court_prestige", "朝堂危机", -15)
    for f in state.factions:
        f.rebellion_risk += 10
        _attr_add(attr, f"{f.name}_rebellion_risk", "朝堂危机", 10)


def _chain_jiangnan(state, attr):
    r = _region(state, "江南", context="_chain_jiangnan")
    if r is None:
        return
    r.stability -= 15
    r.civil_morale -= 10
    r.tax_rate -= 0.2
    _attr_add(attr, "江南_stability", "江南税变", -15)
    _attr_add(attr, "江南_civil_morale", "江南税变", -10)
    _attr_add(attr, "江南_tax_rate", "江南税变", -0.2)
    state.national_treasury += 10
    _attr_add(attr, "national_treasury", "江南税变", 10)


def _time_to_months(year: int, month: int) -> int:
    return (year - 1) * 12 + month


# ── Memorial Trigger System ─────────────────────────────

_URGENCY_PRIORITY = {"critical": 3, "high": 2, "medium": 1}


def _pick_minister_by_loyalty(
    state: GameState,
    faction: str | None = None,
    exclude_faction: str | None = None,
) -> tuple[int, object] | None:
    candidates = []
    for idx, m in enumerate(state.ministers):
        if m.status != MinisterStatus.ACTIVE:
            continue
        if faction is not None and m.faction != faction:
            continue
        if exclude_faction is not None and m.faction == exclude_faction:
            continue
        candidates.append((idx, m))
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x[1].loyalty, -x[0]))


def _pick_minister_by_ability(
    state: GameState,
    ability: str,
    faction: str | None = None,
) -> tuple[int, object] | None:
    candidates = []
    for idx, m in enumerate(state.ministers):
        if m.status != MinisterStatus.ACTIVE:
            continue
        if faction is not None and m.faction != faction:
            continue
        candidates.append((idx, m))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda x: (getattr(x[1].abilities, ability), x[1].loyalty, -x[0]),
    )


def detect_memorial_triggers(state: GameState, attr: dict) -> list[Memorial]:
    current_months = _time_to_months(state.time.year, state.time.month)
    existing_reasons = {
        mem.trigger_reason for mem in state.memorials
        if mem.status in {MemorialStatus.PENDING, MemorialStatus.DEFERRED}
    }
    candidates: list[dict] = []

    def _add(
        ttype: str, entity: str, author: tuple[int, object] | None,
        title: str, urgency: str, deviation: int,
    ) -> None:
        if author is None:
            return
        reason = f"{ttype}:{entity}"
        if reason in existing_reasons:
            return
        if current_months < state.memorial_cooldowns.get(reason, 0):
            return
        idx, minister = author
        candidates.append({
            "priority": _URGENCY_PRIORITY[urgency],
            "deviation": deviation,
            "idx": idx,
            "key": reason,
            "memorial": Memorial(
                id=str(uuid.uuid4()),
                author_name=minister.name,
                author_faction=minister.faction,
                title=title,
                content="待补充奏疏内容。",
                suggested_decrees=[],
                trigger_reason=reason,
                urgency=urgency,
                created_year=state.time.year,
                created_month=state.time.month,
                status=MemorialStatus.PENDING,
            ),
        })

    # 1. faction crisis: satisfaction < 30
    for f in state.factions:
        if f.satisfaction < 30:
            urg = "high" if f.satisfaction < 15 else "medium"
            _add("faction_crisis", f.name,
                 _pick_minister_by_loyalty(state, faction=f.name),
                 f"{f.name}请安抚疏", urg, 30 - f.satisfaction)

    # 2. region crisis: stability < 20
    for r in state.regions:
        if r.stability < 20:
            ability = "military" if r.threat != RegionThreat.NONE else "civil"
            urg = "critical" if r.stability < 10 else "high"
            _add("region_crisis", r.name,
                 _pick_minister_by_ability(state, ability),
                 f"{r.name}危局急报", urg, 20 - r.stability)

    # 3. rebellion warning: rebellion_risk > 60
    for f in state.factions:
        if f.rebellion_risk > 60:
            _add("rebellion_warning", f.name,
                 _pick_minister_by_loyalty(state, exclude_faction=f.name),
                 f"{f.name}叛乱预警疏", "critical", f.rebellion_risk - 60)

    # 4. military crisis: morale < 25 or supply < 20
    morale_crisis = state.military_morale < 25
    supply_crisis = state.military_strength < 20
    if morale_crisis or supply_crisis:
        dev = 0
        if morale_crisis:
            dev += 25 - state.military_morale
        if supply_crisis:
            dev += 20 - state.military_strength
        urg = "critical" if morale_crisis and supply_crisis else "high"
        _add("military_crisis", "national",
             _pick_minister_by_ability(state, "military", faction="辽东边将"),
             "边军军情急报", urg, dev)

    # sort: urgency desc, deviation desc, minister index asc → take top 2
    candidates.sort(key=lambda c: (-c["priority"], -c["deviation"], c["idx"]))
    result: list[Memorial] = []
    seen: set[str] = set()
    for c in candidates:
        key = c["key"]
        if key in seen:
            continue
        result.append(c["memorial"])
        seen.add(key)
        state.memorial_cooldowns[key] = current_months + 3
        if len(result) >= 2:
            break
    return result


def detect_chain_events(state: GameState, attr: dict) -> list[str]:
    current_months = _time_to_months(state.time.year, state.time.month)
    # check phase: all conditions evaluated on same pre-chain state
    to_fire = []
    for evt in CHAIN_EVENTS:
        name = evt["name"]
        cooldown_until = state.event_cooldowns.get(name, 0)
        if current_months < cooldown_until:
            continue
        try:
            should_fire = evt["check"](state)
        except Exception:
            logger.warning(
                "Chain event check failed",
                extra={
                    "entity_type": "chain_event",
                    "entity_name": name,
                    "context": "detect_chain_events:check",
                },
            )
            continue
        if should_fire:
            to_fire.append(evt)
    # apply phase
    triggered = []
    for evt in to_fire:
        name = evt["name"]
        try:
            evt["apply"](state, attr)
        except Exception:
            logger.warning(
                "Chain event apply failed",
                extra={
                    "entity_type": "chain_event",
                    "entity_name": name,
                    "context": "detect_chain_events:apply",
                },
            )
            continue
        triggered.append(name)
        state.event_cooldowns[name] = current_months + 3
    return triggered


def assign_urgency(event_name: str, attr: dict) -> EventUrgency:
    max_mag = 0
    for key, sources in attr.items():
        if isinstance(sources, dict) and event_name in sources:
            max_mag = max(max_mag, abs(sources[event_name]))
    if max_mag > 15:
        return EventUrgency.HIGH
    if max_mag >= 5:
        return EventUrgency.MEDIUM
    return EventUrgency.LOW


_BASE_TAX = {TaxContribution.LOW: 120, TaxContribution.MEDIUM: 220, TaxContribution.HIGH: 360}


def recalc_tax_collected(state: GameState, decree_tax_modifier: float) -> None:
    for r in state.regions:
        r.tax_rate = round(r.tax_rate, 2)
        base = _BASE_TAX[r.tax_contribution]
        stability_factor = r.stability / 100.0
        r.tax_collected = math.floor(base * r.tax_rate * stability_factor * decree_tax_modifier)


def collect_tax_revenue(state: GameState, attr: dict) -> tuple[int, int]:
    """Collect regional tax and split monthly income into silver and grain.
    Fallen regions contribute nothing; unstable regions contribute half.
    Returns (treasury_income, grain_income)."""
    total = 0
    for r in state.regions:
        if r.control == RegionControl.FALLEN:
            continue
        amount = r.tax_collected
        if r.control == RegionControl.UNSTABLE:
            amount = amount // 2
        total += amount
    # scale down: raw sum is per-year base, divide by 12 for monthly income
    monthly_total = max(0, math.floor(total / 12))
    if monthly_total <= 0:
        return 0, 0

    treasury_income = math.floor(monthly_total * 0.7)
    grain_income = monthly_total - treasury_income
    state.national_treasury += treasury_income
    state.grain += grain_income
    _attr_add(attr, "national_treasury", "税收", treasury_income)
    _attr_add(attr, "grain", "税收", grain_income)
    return treasury_income, grain_income


# ── Event Lifecycle ──────────────────────────────────────

def expire_events(state: GameState) -> None:
    current = _time_to_months(state.time.year, state.time.month)
    state.active_events = [
        e for e in state.active_events
        if e.is_scripted or current - _time_to_months(e.triggered_year, e.triggered_month) < 6
    ]


def _script_to_event(se: ScriptEvent, year: int, month: int) -> GameEvent:
    from models.game import EventChoice
    return GameEvent(
        name=se.title,
        description=se.title,
        urgency=EventUrgency.HIGH,
        triggered_year=year,
        triggered_month=month,
        rich_description=se.rich_description,
        choices=[
            EventChoice(
                label=c.label, description=c.description, decrees=c.decrees,
                loyalty_effects=list(c.loyalty_effects),
                state_effects=dict(c.state_effects),
            )
            for c in se.choices
        ],
        is_scripted=True,
        is_blocking=se.is_blocking,
        script_id=se.script_id,
        historical_hint=se.historical_hint,
    )


def inject_script_events(state: GameState) -> list[str]:
    scripts = get_scripts_for_time(state.time.year, state.time.month)
    injected = []
    active_script_ids = {e.script_id for e in state.active_events if e.script_id}
    for se in scripts:
        if se.script_id in active_script_ids or se.script_id in state.resolved_script_ids:
            continue
        if se.condition is not None and not se.condition(state):
            continue
        state.active_events.append(
            _script_to_event(se, state.time.year, state.time.month)
        )
        injected.append(se.title)
    return injected


# ── Time Progression ─────────────────────────────────────

def advance_time(state: GameState) -> None:
    state.time.month += 1
    if state.time.month > 12:
        state.time.year += 1
        state.time.month = 1
    state.time.era_name, state.time.era_year = resolve_era(state.time.year)


# ── Game End Check ───────────────────────────────────────

FINAL_JUDGEMENT_YEAR = 1644
FINAL_JUDGEMENT_MONTH = 3


def _is_final_judgement_time(state: GameState) -> bool:
    if state.time.year > FINAL_JUDGEMENT_YEAR:
        return True
    return state.time.year == FINAL_JUDGEMENT_YEAR and state.time.month >= FINAL_JUDGEMENT_MONTH


def check_game_end(state: GameState) -> dict | None:
    fallen_count = sum(1 for r in state.regions if r.control == RegionControl.FALLEN)
    unstable_count = sum(1 for r in state.regions if r.control == RegionControl.UNSTABLE)

    if fallen_count == len(state.regions):
        return {"result": "defeat", "message": "社稷倾覆，大明亡矣"}
    if fallen_count >= 6:
        return {"result": "defeat", "message": "山河崩裂，六镇沦陷"}
    if fallen_count >= 4 and state.court_prestige < 40:
        return {"result": "defeat", "message": "半壁江山尽失，朝纲不可复支"}
    if state.court_prestige <= 0:
        return {"result": "defeat", "message": "天子威严尽失，朝纲崩坏"}
    if _is_final_judgement_time(state):
        if (fallen_count == 0
                and unstable_count <= 1
                and all(f.rebellion_risk <= 35 for f in state.factions)
                and state.court_prestige >= 70):
            return {"result": "victory", "message": "中兴大明，力挽狂澜"}
        return {"result": "defeat", "message": "甲申之变，历史重演"}
    return None


def _activate_entered_ministers(state: GameState) -> list[str]:
    current = _time_to_months(state.time.year, state.time.month)
    activated: list[str] = []
    for m in state.ministers:
        if m.status != MinisterStatus.NOT_YET_ENTERED:
            continue
        if _time_to_months(m.entry_year, m.entry_month) <= current:
            m.status = MinisterStatus.IDLE if m.position == "" else MinisterStatus.ACTIVE
            activated.append(m.name)
    return activated


def _tick_missions(state: GameState) -> None:
    """Advance on_mission ministers; complete or clear as needed."""
    for m in state.ministers:
        if m.status == MinisterStatus.REMOVED:
            m.current_mission = None
            continue
        if m.status != MinisterStatus.ON_MISSION or m.current_mission is None:
            continue
        m.current_mission.progress_months += 1
        if m.current_mission.progress_months >= m.current_mission.total_months:
            mission = m.current_mission
            # apply effects
            attr: dict = {}
            try:
                apply_ai_effects(state, mission.effects, attr)
            except Exception:
                logger.exception("Mission effect apply failed", extra={"entity_name": m.name, "entity_type": "minister", "context": "_tick_missions"})
            clamp_state(state)
            # complete: clear mission, restore active
            m.current_mission = None
            m.status = MinisterStatus.ACTIVE
            # generate memorial
            memorial = Memorial(
                id=str(uuid.uuid4()),
                author_name=m.name,
                author_faction=m.faction,
                title=f"{m.name}完成任务：{mission.name}",
                content=f"臣{m.name}奉命出使，历时{mission.total_months}月，任务【{mission.name}】已竣事，特此复命。",
                suggested_decrees=[],
                trigger_reason=f"mission_complete:{m.name}",
                urgency="medium",
                created_year=state.time.year,
                created_month=state.time.month,
                status=MemorialStatus.PENDING,
            )
            state.memorials.append(memorial)
            state.history_log.append(HistoryEntry(
                year=state.time.year,
                month=state.time.month,
                decree_type="mission_complete",
                decree_desc=f"{m.name}完成任务：{mission.name}",
                delta={k: v for k, v in mission.effects.items() if isinstance(v, (int, float))},
                narrative=f"{m.name}完成任务【{mission.name}】，归朝复命。",
            ))



def advance_month(state: GameState) -> tuple[list[str], dict | None, list[str]]:
    """Advance game time by one month and inject script events.

    passive_drift stays in process_decree (per-decree), not month advancement.
    Returns (triggered_events, game_over, newly_activated_minister_names).
    """
    advance_time(state)
    state.decrees_this_month = {}
    state.decree_count += 1
    new_ministers = _activate_entered_ministers(state)
    _tick_missions(state)
    triggered_events = inject_script_events(state)
    game_over = check_game_end(state)
    return triggered_events, game_over, new_ministers


# ── AI Freeform: validation & application ─────────────

_STATUS_ENUM_MAP = {
    ("minister", "status"): MinisterStatus,
    ("region", "control"): RegionControl,
    ("region", "threat"): RegionThreat,
}


def _coerce_enum(category: str, field: str, value: str):
    """Convert a string value to the appropriate enum type if applicable."""
    enum_cls = _STATUS_ENUM_MAP.get((category, field))
    if enum_cls is not None:
        try:
            return enum_cls(value)
        except ValueError:
            return value
    return value

def _match_writable_pattern(path: str) -> dict | None:
    """Match a concrete path like 'minister.魏忠贤.loyalty' against WRITABLE_FIELDS patterns."""
    parts = path.split(".")
    for pattern, meta in WRITABLE_FIELDS.items():
        pparts = pattern.split(".")
        if len(parts) != len(pparts):
            continue
        if all(pp == "*" or pp == cp for pp, cp in zip(pparts, parts)):
            return meta
    return None


def _resolve_entity(state: GameState, category: str, name: str):
    """Resolve an entity by category and name. Returns the object or None."""
    if category == "minister":
        return next((m for m in state.ministers if m.name == name), None)
    if category == "faction":
        return next((f for f in state.factions if f.name == name), None)
    if category == "region":
        return next((r for r in state.regions if r.name == name), None)
    return None


def validate_ai_effects(effects: dict, state: GameState) -> dict:
    """Validate AI effects against whitelist. Returns cleaned dict of valid entries only."""
    if not isinstance(effects, dict):
        return {}
    valid: dict = {}
    for path, value in effects.items():
        if not isinstance(path, str):
            continue
        # reject nested / non-scalar values
        if isinstance(value, (dict, list)):
            continue
        meta = _match_writable_pattern(path)
        if meta is None:
            continue
        parts = path.split(".")
        category = parts[0]
        # global fields
        if category == "global":
            field = parts[1] if len(parts) == 2 else None
            if field is None or not hasattr(state, field):
                continue
        # entity fields: verify name exists
        elif category in ("minister", "faction", "region"):
            if len(parts) < 3:
                continue
            name = parts[1]
            entity = _resolve_entity(state, category, name)
            if entity is None:
                continue
            # minister status transition validation
            if category == "minister" and parts[-1] == "status":
                if not isinstance(value, str):
                    continue
                current = entity.status.value if hasattr(entity.status, "value") else str(entity.status)
                if (current, value) not in VALID_STATUS_TRANSITIONS:
                    continue
        else:
            continue
        # type check
        expected_type = meta["type"]
        if expected_type in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
        elif expected_type == "str":
            if not isinstance(value, str):
                continue
            valid_values = meta.get("valid")
            if valid_values and value not in valid_values:
                continue
        valid[path] = value
    return valid


def apply_ai_effects(
    state: GameState, effects: dict, attr: dict,
) -> tuple[set[str], set[str]]:
    """Apply validated AI effects to GameState. Returns (dismissed_names, executed_names)."""
    dismissed: set[str] = set()
    executed: set[str] = set()

    numeric_entries = []
    status_entries = []
    for path, value in effects.items():
        meta = _match_writable_pattern(path)
        if meta is None:
            continue
        if meta["type"] in ("int", "float"):
            numeric_entries.append((path, value, meta))
        else:
            status_entries.append((path, value, meta))

    # Round 1: numeric deltas
    for path, value, meta in numeric_entries:
        parts = path.split(".")
        category = parts[0]
        attr_key = "_".join(parts[1:]) if category != "global" else parts[1]

        if category == "global":
            field = parts[1]
            old = getattr(state, field)
            setattr(state, field, old + value)
            if meta["type"] == "float":
                setattr(state, field, round(getattr(state, field), 2))
        else:
            name = parts[1]
            entity = _resolve_entity(state, category, name)
            if entity is None:
                continue
            attr_key = f"{name}_{'_'.join(parts[2:])}"
            # depth-4: minister.X.abilities.Y
            if category == "minister" and len(parts) == 4 and parts[2] == "abilities":
                ability_field = parts[3]
                old = getattr(entity.abilities, ability_field)
                setattr(entity.abilities, ability_field, old + value)
            else:
                field = parts[2]
                old = getattr(entity, field)
                new_val = old + value
                if meta["type"] == "float":
                    new_val = round(new_val, 2)
                setattr(entity, field, new_val)

        _attr_add(attr, attr_key, "旨意影响", value)

    # Round 2: string/status sets
    for path, value, meta in status_entries:
        parts = path.split(".")
        category = parts[0]
        name = parts[1]
        field = parts[2]
        entity = _resolve_entity(state, category, name)
        if entity is None:
            continue

        # convert string to enum where needed
        actual_value = _coerce_enum(category, field, value)
        attr_key = f"{name}_{field}"
        setattr(entity, field, actual_value)
        attr.setdefault(attr_key, {})["旨意影响"] = value

        if category == "minister" and field == "status":
            if value == "removed":
                executed.add(name)
            elif value == "idle":
                dismissed.add(name)

    return dismissed, executed


def add_ai_new_events(state: GameState, new_events: list) -> None:
    """Validate and add AI-created events to active_events. Max 3 per turn."""
    if not isinstance(new_events, list):
        return
    added = 0
    for evt in new_events:
        if added >= 3:
            break
        if isinstance(evt, GameEvent):
            cur = _time_to_months(state.time.year, state.time.month)
            evt_t = _time_to_months(evt.triggered_year, evt.triggered_month)
            if evt_t < cur:
                logger.warning("add_ai_new_events: triggered time in past, discarding", extra={"entity_name": evt.name, "entity_type": "event", "context": "add_ai_new_events"})
                continue
            if evt_t > cur:
                evt.triggered_year = state.time.year
                evt.triggered_month = state.time.month
            state.active_events.append(evt)
            added += 1
            continue
        if not isinstance(evt, dict):
            continue
        name = evt.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        urgency_raw = evt.get("urgency", "中")
        if urgency_raw not in ("高", "中", "低"):
            urgency_raw = "中"
        description = str(evt.get("description", ""))
        state.active_events.append(GameEvent(
            name=name.strip(),
            description=description,
            urgency=EventUrgency(urgency_raw),
            triggered_year=state.time.year,
            triggered_month=state.time.month,
        ))
        added += 1


_MISSION_TOTAL_MONTHS_RANGE = (2, 12)


def _apply_mission_decree(state: GameState, freeform: FreeformResult) -> bool:
    """Handle _mission_<name> key in freeform effects. Returns True if handled."""
    mission_key = next(
        (k for k in freeform.effects if isinstance(k, str) and k.startswith("_mission_")),
        None,
    )
    if mission_key is None:
        return False
    minister_name = mission_key[len("_mission_"):]
    minister = next((m for m in state.ministers if m.name == minister_name), None)
    if minister is None or minister.status != MinisterStatus.ACTIVE:
        logger.warning("Mission decree: minister not active", extra={"entity_name": minister_name, "entity_type": "minister", "context": "_apply_mission_decree"})
        return False

    payload = freeform.effects.get(mission_key)
    if not isinstance(payload, dict):
        return False

    mission_name = str(payload.get("name", "")).strip()
    if not mission_name:
        return False
    try:
        total_months = int(payload.get("total_months", 0))
    except (TypeError, ValueError):
        return False
    if not (_MISSION_TOTAL_MONTHS_RANGE[0] <= total_months <= _MISSION_TOTAL_MONTHS_RANGE[1]):
        return False
    try:
        cost = int(payload.get("cost", 0))
    except (TypeError, ValueError):
        cost = 0
    if cost < 0:
        return False
    if state.national_treasury < cost:
        return False

    raw_effects = payload.get("effects", {})
    if not isinstance(raw_effects, dict):
        raw_effects = {}
    valid_effects = validate_ai_effects(raw_effects, state)

    state.national_treasury -= cost
    minister.status = MinisterStatus.ON_MISSION
    minister.current_mission = MissionState(
        name=mission_name,
        progress_months=0,
        total_months=total_months,
        cost=cost,
        effects=valid_effects,
    )
    return True




def process_decree(
    state: GameState,
    decree: StructuredDecree | None = None,
    freeform: FreeformResult | None = None,
) -> tuple[dict, dict, list[str], dict | None, list[MinisterReaction], TurnSummary]:
    """Execute one policy resolution pipeline and return its full outcome.

    Returns:
    (delta, attribution, triggered_events, game_over, minister_reactions, turn_summary)

    Notes:
    - ``decree is None`` and ``freeform is None`` is treated as a wait turn.
    - Structured and freeform branches both merge into the same downstream chain:
      chain events -> clamp -> region control -> tax/revenue -> memorial/event updates.
    """
    attr: dict = {}
    reactions: list[MinisterReaction] = []

    # snapshot before passive_drift (for turn summary)
    before_snapshot = state.model_dump()

    # 1. passive drift
    apply_passive_drift(state, attr)

    # 1.5 consecutive wait penalty
    if decree is None and freeform is None:
        state.consecutive_waits += 1
        if state.consecutive_waits >= CONSECUTIVE_WAIT_THRESHOLD:
            state.court_prestige -= WAIT_PRESTIGE_PENALTY
            state.civil_morale -= WAIT_MORALE_PENALTY
            _attr_add(attr, "court_prestige", "怠政", -WAIT_PRESTIGE_PENALTY)
            _attr_add(attr, "civil_morale", "怠政", -WAIT_MORALE_PENALTY)
    else:
        state.consecutive_waits = 0

    decree_tax_modifier = 1.0

    if freeform is not None:
        # ── Freeform branch ──
        # handle _mission_<name> key before standard effects
        _apply_mission_decree(state, freeform)
        # validate + apply AI effects (skip _mission_ keys)
        filtered_effects = {k: v for k, v in freeform.effects.items() if not k.startswith("_mission_")}
        valid_effects = validate_ai_effects(filtered_effects, state)
        dismissed, executed = apply_ai_effects(state, valid_effects, attr)

        # execution backlash (same logic as structured path)
        for name in executed:
            target_m = next((m for m in state.ministers if m.name == name), None)
            if target_m:
                for f in state.factions:
                    if f.name == target_m.faction:
                        f.satisfaction -= EXECUTION_SATISFACTION_PENALTY
                        f.rebellion_risk += EXECUTION_REBELLION_RISK
                        _attr_add(attr, f"{f.name}_satisfaction", "execution_backlash", -EXECUTION_SATISFACTION_PENALTY)
                        _attr_add(attr, f"{f.name}_rebellion_risk", "execution_backlash", EXECUTION_REBELLION_RISK)

        # reactions from AI (validated)
        reactions = _validate_freeform_reactions(freeform.reactions, state)
        # freeform tax modifier = 1.0 (AI effects already include region changes)
        decree_tax_modifier = 1.0

    elif decree:
        # ── Structured branch (unchanged) ──
        # 2. base effects
        apply_base_effects(state, decree, attr)
        # 3. faction reactions
        apply_faction_reactions(state, decree, attr)
        # 3.5 minister status transition
        dismissed, executed = apply_minister_transition(state, decree)
        # 3.5.1 execution faction backlash
        for name in executed:
            target_m = next((m for m in state.ministers if m.name == name), None)
            if target_m:
                for f in state.factions:
                    if f.name == target_m.faction:
                        f.satisfaction -= EXECUTION_SATISFACTION_PENALTY
                        f.rebellion_risk += EXECUTION_REBELLION_RISK
                        _attr_add(attr, f"{f.name}_satisfaction", "execution_backlash", -EXECUTION_SATISFACTION_PENALTY)
                        _attr_add(attr, f"{f.name}_rebellion_risk", "execution_backlash", EXECUTION_REBELLION_RISK)
        # 3.6 loyalty modification
        apply_loyalty_modification(state, decree, attr, dismissed)
        # 3.7 minister reactions
        reactions = generate_minister_reactions(state, decree, attr)
        # 4. region impact
        decree_tax_modifier = apply_region_impact(state, decree, attr)

    # ── Merge point: shared pipeline ──
    # 5. chain events
    triggered = detect_chain_events(state, attr)
    # 6. clamp
    clamp_state(state)
    # 6.1 region control (before tax so fallen regions stop paying)
    update_region_control(state)
    # 6.2 cascading impact from territorial loss
    apply_region_control_consequences(state, attr)
    clamp_state(state)
    # 6.3 tax recalculation & revenue (uses up-to-date control state)
    recalc_tax_collected(state, decree_tax_modifier)
    collect_tax_revenue(state, attr)
    clamp_state(state)
    if decree and decree.type.value in _MONTHLY_LIMITED:
        state.decrees_this_month[decree.type.value] = True
    # after_snapshot for turn summary (post-clamp)
    after_snapshot = state.model_dump()
    # 6.5 memorial triggers (post-clamp)
    triggered_memorials = detect_memorial_triggers(state, attr)
    if triggered_memorials:
        state.memorials.extend(triggered_memorials)
    # expire old events
    expire_events(state)
    # add chain-triggered events
    for ename in triggered:
        state.active_events.append(GameEvent(
            name=ename,
            urgency=assign_urgency(ename, attr),
            triggered_year=state.time.year,
            triggered_month=state.time.month,
        ))
    # add AI new events (freeform only)
    if freeform is not None:
        add_ai_new_events(state, freeform.new_events)
    # rebellion risk warning events
    for f in state.factions:
        if f.rebellion_risk > 80:
            warning_name = f"{f.name}叛乱预警"
            if not any(e.name == warning_name for e in state.active_events):
                state.active_events.append(GameEvent(
                    name=warning_name, urgency=EventUrgency.HIGH,
                    triggered_year=state.time.year, triggered_month=state.time.month,
                ))
    # time advancement removed - now in advance_month()
    game_over = None
    # delta (full before/after decree pipeline, without time advance)
    after = state.model_dump()
    delta = _compute_delta(before_snapshot, after)
    # turn summary (uses post-clamp snapshots per D17)
    summary = generate_turn_summary(
        before_snapshot,
        after_snapshot,
        triggered,
        reactions,
        state,
        decree=decree,
        freeform=freeform,
        attr=attr,
    )

    return delta, attr, triggered, game_over, reactions, summary


def _validate_freeform_reactions(
    raw_reactions: list[MinisterReaction], state: GameState,
) -> list[MinisterReaction]:
    """Validate AI-provided reactions: drop invalid minister refs, fill defaults."""
    active_names = {
        m.name: m for m in state.ministers
        if m.status in {MinisterStatus.ACTIVE, MinisterStatus.IDLE}
    }
    validated: list[MinisterReaction] = []
    for r in raw_reactions:
        if r.minister_name not in active_names:
            continue
        minister = active_names[r.minister_name]
        reaction_type = (r.reaction_type or "neutral").strip().lower()
        if reaction_type not in {"support", "oppose", "neutral"}:
            reaction_type = "neutral"
        validated.append(MinisterReaction(
            minister_name=r.minister_name,
            faction=r.faction or minister.faction,
            reaction_type=reaction_type,
            reaction_text=r.reaction_text or f"{r.minister_name}：臣遵旨。",
            loyalty_change=r.loyalty_change or 0,
        ))
    return validated


# ── Turn Summary ────────────────────────────────────────

_GLOBAL_INDICATORS = ("national_treasury", "imperial_treasury", "grain", "population", "military_strength", "civil_morale", "military_morale", "court_prestige")
_PENDING_STATUSES = {MemorialStatus.PENDING.value, MemorialStatus.DEFERRED.value}
_INDICATOR_LABELS = {
    "national_treasury": "国库",
    "imperial_treasury": "内帑",
    "grain": "粮储",
    "population": "人口",
    "military_strength": "军力",
    "civil_morale": "民心",
    "military_morale": "军心",
    "court_prestige": "朝廷威望",
}
_MINISTER_STATUS_LABELS = {
    "active": "在朝",
    "idle": "闲置",
    "removed": "革除",
    "not_yet_entered": "未入朝",
}


def _describe_decree_action(decree: StructuredDecree) -> str:
    if decree.type == DecreeType.TAX_INCREASE:
        return "下旨加征赋税，试图补强国库"
    if decree.type == DecreeType.TAX_DECREASE:
        return "下旨减免赋税，以安抚民生"
    if decree.type == DecreeType.RECRUIT_TROOPS:
        return "下旨征兵备战，强化边防"
    if decree.type == DecreeType.DISBAND_TROOPS:
        return "下旨裁撤兵员，缓解财政压力"
    if decree.type == DecreeType.DIPLOMACY:
        target = decree.target or "外邦"
        return f"下旨调整对{target}外交策略"
    if decree.type == DecreeType.DISASTER_RELIEF:
        target = decree.target or "灾区"
        return f"下旨赈济{target}，缓和灾情"
    if decree.type == DecreeType.HARSH_PUNISHMENT:
        return "下旨严刑峻法，整肃朝纲"
    if decree.type == DecreeType.PERSONNEL:
        target = decree.target or "相关官员"
        if decree.sub_action == PersonnelAction.EXECUTE:
            return f"下旨处决{target}，朝堂震动"
        if decree.sub_action == PersonnelAction.DISMISS:
            return f"下旨罢免{target}，调整权力格局"
        if decree.sub_action == PersonnelAction.APPOINT:
            return f"下旨起用{target}，重整用人布局"
        return "下旨调整人事，重排朝班"
    return "下旨处理政务，朝局随之变化"


def _build_action_implications(
    indicator_trends: list[IndicatorTrend],
    minister_changes: list[MinisterChange],
    faction_changes: list[FactionChange],
    decree: StructuredDecree | None,
    freeform: FreeformResult | None,
) -> list[str]:
    implications: list[str] = []

    if decree is not None:
        implications.append(_describe_decree_action(decree))
    elif freeform is not None:
        rationale = (freeform.rationale or "").strip()
        if rationale:
            implications.append(f"本回合政务主旨：{rationale}")
        else:
            implications.append("本回合颁布自由政令，朝局产生连锁变化")
    else:
        implications.append("本月未颁布新政令，朝局以惯性运转")

    ranked_indicators = sorted(
        indicator_trends,
        key=lambda x: abs(x.after - x.before),
        reverse=True,
    )
    for trend in ranked_indicators[:3]:
        delta = trend.after - trend.before
        if delta == 0:
            continue
        label = _INDICATOR_LABELS.get(trend.name, trend.name)
        direction = "上升" if delta > 0 else "下降"
        implications.append(f"{label}{direction}{abs(delta)}")

    status_changes = [m for m in minister_changes if m.status_before != m.status_after]
    for change in status_changes[:2]:
        before_status = _MINISTER_STATUS_LABELS.get(change.status_before, change.status_before)
        after_status = _MINISTER_STATUS_LABELS.get(change.status_after, change.status_after)
        implications.append(f"{change.name}由{before_status}转为{after_status}")

    risk_changes = sorted(
        faction_changes,
        key=lambda x: abs((x.rebellion_risk_after - x.rebellion_risk_before)),
        reverse=True,
    )
    if risk_changes:
        top = risk_changes[0]
        delta = top.rebellion_risk_after - top.rebellion_risk_before
        if delta != 0:
            direction = "上升" if delta > 0 else "下降"
            implications.append(f"{top.name}叛乱风险{direction}{abs(delta)}")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in implications:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= 6:
            break
    return deduped


_REGION_NUMERIC_FIELDS = (
    "stability", "garrison", "civil_morale", "rebellion_risk",
    "disaster_level", "tax_collected", "tax_rate",
)
_REGION_ALL_FIELDS = (
    "stability", "garrison", "control", "threat",
    "civil_morale", "rebellion_risk", "disaster_level",
    "tax_collected", "tax_rate", "tax_contribution",
)


def generate_turn_summary(
    before: dict, after: dict,
    triggered: list[str], reactions: list[MinisterReaction],
    state: GameState,
    decree: StructuredDecree | None = None,
    freeform: FreeformResult | None = None,
    attr: dict | None = None,
) -> TurnSummary:
    indicator_trends = [
        IndicatorTrend(name=k, before=before[k], after=after[k])
        for k in _GLOBAL_INDICATORS if before[k] != after[k]
    ]

    bf_map = {f["name"]: f for f in before.get("factions", [])}
    faction_changes = []
    for af in after.get("factions", []):
        bf = bf_map.get(af["name"])
        if bf is None:
            continue
        if bf["satisfaction"] != af["satisfaction"] or bf["rebellion_risk"] != af["rebellion_risk"]:
            faction_changes.append(FactionChange(
                name=af["name"],
                satisfaction_before=bf["satisfaction"], satisfaction_after=af["satisfaction"],
                rebellion_risk_before=bf["rebellion_risk"], rebellion_risk_after=af["rebellion_risk"],
            ))

    br_map = {r["name"]: r for r in before.get("regions", [])}
    region_changes = []
    for ar in after.get("regions", []):
        br = br_map.get(ar["name"])
        if br is None:
            continue
        has_change = any(br.get(f) != ar.get(f) for f in _REGION_ALL_FIELDS)
        if not has_change:
            continue
        rc = RegionChange(
            name=ar["name"],
            stability_before=br["stability"], stability_after=ar["stability"],
            control_before=br["control"], control_after=ar["control"],
            threat_before=br["threat"], threat_after=ar["threat"],
        )
        if br.get("garrison") != ar.get("garrison"):
            rc.garrison_before = br["garrison"]
            rc.garrison_after = ar["garrison"]
        if br.get("civil_morale") != ar.get("civil_morale"):
            rc.civil_morale_before = br["civil_morale"]
            rc.civil_morale_after = ar["civil_morale"]
        if br.get("rebellion_risk") != ar.get("rebellion_risk"):
            rc.rebellion_risk_before = br["rebellion_risk"]
            rc.rebellion_risk_after = ar["rebellion_risk"]
        if br.get("disaster_level") != ar.get("disaster_level"):
            rc.disaster_level_before = br["disaster_level"]
            rc.disaster_level_after = ar["disaster_level"]
        if br.get("tax_collected") != ar.get("tax_collected"):
            rc.tax_collected_before = br["tax_collected"]
            rc.tax_collected_after = ar["tax_collected"]
        if br.get("tax_rate") != ar.get("tax_rate"):
            rc.tax_rate_before = br["tax_rate"]
            rc.tax_rate_after = ar["tax_rate"]
        if br.get("tax_contribution") != ar.get("tax_contribution"):
            rc.tax_contribution_before = br["tax_contribution"]
            rc.tax_contribution_after = ar["tax_contribution"]
        region_changes.append(rc)

    bm_map = {m["name"]: m for m in before.get("ministers", [])}
    minister_changes = []
    for am in after.get("ministers", []):
        bm = bm_map.get(am["name"])
        if bm is None:
            continue
        if bm["loyalty"] != am["loyalty"] or bm["status"] != am["status"]:
            minister_changes.append(MinisterChange(
                name=am["name"],
                loyalty_before=bm["loyalty"], loyalty_after=am["loyalty"],
                status_before=bm["status"], status_after=am["status"],
            ))

    # Build region_details from attr dict
    region_details: list[RegionDetail] | None = None
    if attr:
        details: list[RegionDetail] = []
        region_names = {r["name"] for r in after.get("regions", [])}
        for key, sources in attr.items():
            if not isinstance(sources, dict):
                continue
            # Parse "{region}_{field}" keys
            for rname in region_names:
                if key.startswith(f"{rname}_"):
                    field = key[len(rname) + 1:]
                    if field in _REGION_NUMERIC_FIELDS:
                        for source, delta in sources.items():
                            if delta != 0:
                                details.append(RegionDetail(
                                    region=rname, field=field,
                                    delta=float(delta), source=source,
                                ))
                    break
        if details:
            details.sort(key=lambda d: d.region)
            region_details = details

    pending_count = sum(1 for m in state.memorials if m.status.value in _PENDING_STATUSES)
    action_implications = _build_action_implications(
        indicator_trends,
        minister_changes,
        faction_changes,
        decree,
        freeform,
    )

    t = after.get("time", {})
    return TurnSummary(
        year=t.get("year", state.time.year),
        month=t.get("month", state.time.month),
        era_name=t.get("era_name", state.time.era_name),
        era_year=t.get("era_year", state.time.era_year),
        major_events=list(triggered),
        action_implications=action_implications,
        indicator_trends=indicator_trends,
        faction_changes=faction_changes,
        region_changes=region_changes,
        minister_changes=minister_changes,
        region_details=region_details,
        pending_memorials_count=pending_count,
    )


def _compute_delta(before: dict, after: dict) -> dict:
    delta = {}
    for key in ("national_treasury", "imperial_treasury", "grain", "population", "military_strength", "civil_morale", "military_morale", "court_prestige"):
        d = after[key] - before[key]
        if d != 0:
            delta[key] = d
    for i, (bf, af) in enumerate(zip(before["factions"], after["factions"])):
        name = bf["name"]
        for field in ("satisfaction", "rebellion_risk"):
            d = af[field] - bf[field]
            if d != 0:
                delta[f"{name}_{field}"] = d
    for i, (br, ar) in enumerate(zip(before["regions"], after["regions"])):
        name = br["name"]
        for field in ("stability", "garrison", "civil_morale", "rebellion_risk", "tax_collected", "disaster_level"):
            d = ar[field] - br[field]
            if d != 0:
                delta[f"{name}_{field}"] = d
        tax_d = ar["tax_rate"] - br["tax_rate"]
        if abs(tax_d) > 1e-9:
            delta[f"{name}_tax_rate"] = round(tax_d, 4)
    return delta
