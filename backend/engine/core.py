from __future__ import annotations

import math
from copy import deepcopy

from models.game import (
    GameState, StructuredDecree, DecreeResponse, GameTime,
    GameEvent, HistoryEntry, clamp_state,
)
from models.enums import DecreeType, RegionControl, RegionThreat, EventUrgency
from .tables import (
    DECREE_EFFECTS, FACTION_STANCE, DECREE_PRECONDITIONS,
    DECREE_TARGET_REQUIRED, REGION_NAMES, DIPLOMACY_TARGETS,
    PRECONDITION_MESSAGES, TARGET_MISSING_MESSAGES,
)


# ── Attribution helper ───────────────────────────────────

def _attr_add(attr: dict, key: str, source: str, value: int) -> None:
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
                "treasury": state.treasury, "population": state.population,
                "military_supply": state.military_supply, "civil_morale": state.civil_morale,
                "military_morale": state.military_morale, "court_prestige": state.court_prestige,
            })
    return None


def validate_target(decree: StructuredDecree) -> str | None:
    req = DECREE_TARGET_REQUIRED.get(decree.type)
    if req is None:
        return None
    if req == "region":
        if not decree.target or decree.target not in REGION_NAMES:
            return TARGET_MISSING_MESSAGES[decree.type]
    elif req == "person":
        if not decree.target or not decree.sub_action:
            return TARGET_MISSING_MESSAGES[decree.type]
    elif req == "diplomacy_target":
        if not decree.target or decree.target not in DIPLOMACY_TARGETS:
            return TARGET_MISSING_MESSAGES[decree.type]
    return None


# ── Passive Drift ────────────────────────────────────────

def apply_passive_drift(state: GameState, attr: dict) -> None:
    for r in state.regions:
        if r.threat != RegionThreat.NONE:
            r.stability -= 3
            _attr_add(attr, f"{r.name}_stability", "passive_drift", -3)
    if state.treasury < 50:
        state.military_morale -= 1
        _attr_add(attr, "military_morale", "passive_drift", -1)
    if any(r.stability < 20 for r in state.regions):
        state.civil_morale -= 2
        _attr_add(attr, "civil_morale", "passive_drift", -2)
    if any(f.rebellion_risk > 60 for f in state.factions):
        state.court_prestige -= 1
        _attr_add(attr, "court_prestige", "passive_drift", -1)


# ── Base Effects ─────────────────────────────────────────

def apply_base_effects(state: GameState, decree: StructuredDecree, attr: dict) -> None:
    effects = DECREE_EFFECTS[decree.type]
    for field, delta in effects.items():
        if delta == 0:
            continue
        setattr(state, field, getattr(state, field) + delta)
        _attr_add(attr, field, "base_effect", delta)


# ── Faction Reactions ────────────────────────────────────

def apply_faction_reactions(state: GameState, decree: StructuredDecree, attr: dict) -> None:
    for faction in state.factions:
        stance = FACTION_STANCE.get(faction.name, {})
        modifier = stance.get(decree.type, 0)
        if modifier == 0:
            continue
        sat_change = math.floor(modifier * faction.influence / 100)
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


# ── Region Impact ────────────────────────────────────────

def apply_region_impact(state: GameState, decree: StructuredDecree, attr: dict) -> None:
    dt = decree.type
    for r in state.regions:
        if dt == DecreeType.TAX_INCREASE:
            if r.stability < 30:
                penalty = -15
            elif r.stability < 60:
                penalty = -8
            else:
                penalty = -5
            r.stability += penalty
            _attr_add(attr, f"{r.name}_stability", "region_impact", penalty)
        elif dt == DecreeType.TAX_DECREASE:
            r.stability += 3
            _attr_add(attr, f"{r.name}_stability", "region_impact", 3)
        elif dt == DecreeType.RECRUIT_TROOPS:
            if r.threat != RegionThreat.NONE:
                r.stability += 5
                r.garrison += 2000
                _attr_add(attr, f"{r.name}_stability", "region_impact", 5)
                _attr_add(attr, f"{r.name}_garrison", "region_impact", 2000)
        elif dt == DecreeType.DISBAND_TROOPS:
            if r.garrison > 10000:
                r.garrison -= 3000
                _attr_add(attr, f"{r.name}_garrison", "region_impact", -3000)
        elif dt == DecreeType.DISASTER_RELIEF:
            if decree.target and r.name == decree.target:
                r.stability += 20
                _attr_add(attr, f"{r.name}_stability", "region_impact", 20)
        elif dt == DecreeType.HARSH_PUNISHMENT:
            if r.stability < 40:
                r.stability -= 8
                _attr_add(attr, f"{r.name}_stability", "region_impact", -8)
            elif r.stability >= 60:
                r.stability += 3
                _attr_add(attr, f"{r.name}_stability", "region_impact", 3)


# ── Region Control State Machine ─────────────────────────

def update_region_control(state: GameState) -> None:
    for r in state.regions:
        if r.control == RegionControl.COURT and r.stability < 10:
            r.control = RegionControl.UNSTABLE
        elif r.control == RegionControl.UNSTABLE and r.stability == 0:
            r.control = RegionControl.FALLEN
        elif r.control == RegionControl.UNSTABLE and r.stability > 30:
            r.control = RegionControl.COURT


# ── Chain Events ─────────────────────────────────────────

CHAIN_EVENTS = [
    {
        "name": "流寇势力扩大",
        "check": lambda s: _region(s, "陕西").stability < 20 and s.civil_morale < 40,
        "apply": lambda s, a: _chain_apply(s, a, "流寇势力扩大", [("陕西", "stability", -5), ("中原", "stability", -10)]),
    },
    {
        "name": "边军哗变",
        "check": lambda s: s.military_morale < 25 and s.treasury < 20,
        "apply": lambda s, a: _chain_apply(s, a, "边军哗变", [("辽东", "stability", -20)], faction_effects=[("边将势力", "rebellion_risk", 25)]),
    },
    {
        "name": "朝堂危机",
        "check": lambda s: any(f.rebellion_risk > 80 for f in s.factions) and s.court_prestige < 30,
        "apply": lambda s, a: _chain_crisis(s, a),
    },
    {
        "name": "江南税变",
        "check": lambda s: s.treasury < 10 and _region(s, "江南").stability > 50,
        "apply": lambda s, a: _chain_jiangnan(s, a),
    },
    {
        "name": "后金入寇",
        "check": lambda s: _region(s, "辽东").stability < 15 and s.military_supply < 30,
        "apply": lambda s, a: _chain_apply(s, a, "后金入寇", [("辽东", "stability", -20), ("京畿", "stability", -10)], global_effects=[("military_morale", -15)]),
    },
]


def _region(state: GameState, name: str):
    return next(r for r in state.regions if r.name == name)


def _chain_apply(state, attr, event_name, region_effects, faction_effects=None, global_effects=None):
    for rname, field, delta in region_effects:
        r = _region(state, rname)
        setattr(r, field, getattr(r, field) + delta)
        _attr_add(attr, f"{rname}_{field}", "chain_event", delta)
    for fname, field, delta in (faction_effects or []):
        f = next(fc for fc in state.factions if fc.name == fname)
        setattr(f, field, getattr(f, field) + delta)
        _attr_add(attr, f"{fname}_{field}", "chain_event", delta)
    for field, delta in (global_effects or []):
        setattr(state, field, getattr(state, field) + delta)
        _attr_add(attr, field, "chain_event", delta)


def _chain_crisis(state, attr):
    state.court_prestige -= 15
    _attr_add(attr, "court_prestige", "chain_event", -15)
    for f in state.factions:
        f.rebellion_risk += 10
        _attr_add(attr, f"{f.name}_rebellion_risk", "chain_event", 10)


def _chain_jiangnan(state, attr):
    r = _region(state, "江南")
    r.stability -= 15
    _attr_add(attr, "江南_stability", "chain_event", -15)
    state.treasury += 10
    _attr_add(attr, "treasury", "chain_event", 10)


def _time_to_months(year: int, month: int) -> int:
    return (year - 1) * 12 + month


def detect_chain_events(state: GameState, attr: dict) -> list[str]:
    triggered = []
    current_months = _time_to_months(state.time.year, state.time.month)
    for evt in CHAIN_EVENTS:
        name = evt["name"]
        cooldown_until = state.event_cooldowns.get(name, 0)
        if current_months <= cooldown_until:
            continue
        if evt["check"](state):
            evt["apply"](state, attr)
            triggered.append(name)
            state.event_cooldowns[name] = current_months + 3
    return triggered


def assign_urgency(event_name: str, attr: dict) -> EventUrgency:
    max_mag = 0
    for key, sources in attr.items():
        if isinstance(sources, dict) and "chain_event" in sources:
            max_mag = max(max_mag, abs(sources["chain_event"]))
    if max_mag > 15:
        return EventUrgency.HIGH
    if max_mag >= 5:
        return EventUrgency.MEDIUM
    return EventUrgency.LOW


# ── Event Lifecycle ──────────────────────────────────────

def expire_events(state: GameState) -> None:
    current = _time_to_months(state.time.year, state.time.month)
    state.active_events = [
        e for e in state.active_events
        if current - _time_to_months(e.triggered_year, e.triggered_month) < 6
    ]


# ── Time Progression ─────────────────────────────────────

def advance_time(state: GameState) -> None:
    state.time.month += 1
    if state.time.month > 12:
        state.time.year += 1
        state.time.month = 1


# ── Game End Check ───────────────────────────────────────

FINAL_JUDGEMENT_YEAR = 17
FINAL_JUDGEMENT_MONTH = 3


def _is_final_judgement_time(state: GameState) -> bool:
    if state.time.year > FINAL_JUDGEMENT_YEAR:
        return True
    return state.time.year == FINAL_JUDGEMENT_YEAR and state.time.month >= FINAL_JUDGEMENT_MONTH


def check_game_end(state: GameState) -> dict | None:
    if all(r.control == RegionControl.FALLEN for r in state.regions):
        return {"result": "defeat", "message": "社稷倾覆，大明亡矣"}
    if state.court_prestige <= 0:
        return {"result": "defeat", "message": "天子威严尽失，朝纲崩坏"}
    if _is_final_judgement_time(state):
        if (all(r.control == RegionControl.COURT for r in state.regions)
                and all(f.rebellion_risk <= 20 for f in state.factions)
                and state.court_prestige > 80):
            return {"result": "victory", "message": "中兴大明，力挽狂澜"}
        return {"result": "defeat", "message": "甲申之变，历史重演"}
    return None


# ── Main Pipeline ────────────────────────────────────────

def process_decree(state: GameState, decree: StructuredDecree) -> tuple[dict, dict, list[str], dict | None]:
    """Returns (delta, attribution, triggered_events, game_over)."""
    attr: dict = {}

    # snapshot before
    before = state.model_dump()

    # 1. passive drift
    apply_passive_drift(state, attr)
    # 2. base effects
    apply_base_effects(state, decree, attr)
    # 3. faction reactions
    apply_faction_reactions(state, decree, attr)
    # 4. region impact
    apply_region_impact(state, decree, attr)
    # 5. chain events
    triggered = detect_chain_events(state, attr)
    # 6. clamp
    clamp_state(state)
    # region control
    update_region_control(state)
    # expire old events
    expire_events(state)
    # add new events
    for ename in triggered:
        state.active_events.append(GameEvent(
            name=ename,
            urgency=assign_urgency(ename, attr),
            triggered_year=state.time.year,
            triggered_month=state.time.month,
        ))
    # rebellion risk warning events
    for f in state.factions:
        if f.rebellion_risk > 80:
            warning_name = f"{f.name}叛乱预警"
            if not any(e.name == warning_name for e in state.active_events):
                state.active_events.append(GameEvent(
                    name=warning_name, urgency=EventUrgency.HIGH,
                    triggered_year=state.time.year, triggered_month=state.time.month,
                ))
    # time
    advance_time(state)
    state.decree_count += 1
    # game end
    game_over = check_game_end(state)
    # delta
    after = state.model_dump()
    delta = _compute_delta(before, after)

    return delta, attr, triggered, game_over


def _compute_delta(before: dict, after: dict) -> dict:
    delta = {}
    for key in ("treasury", "population", "military_supply", "civil_morale", "military_morale", "court_prestige"):
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
        for field in ("stability", "garrison"):
            d = ar[field] - br[field]
            if d != 0:
                delta[f"{name}_{field}"] = d
    return delta
