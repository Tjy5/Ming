from __future__ import annotations

import math
import uuid

from models.game import (
    GameState, StructuredDecree, DecreeResponse, GameTime,
    GameEvent, HistoryEntry, MinisterReaction, Memorial,
    TurnSummary, IndicatorTrend, FactionChange, RegionChange, MinisterChange,
    FreeformResult,
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
)
from .scripts import get_scripts_for_time, ScriptEvent


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
                "treasury": state.treasury, "population": state.population,
                "military_supply": state.military_supply, "civil_morale": state.civil_morale,
                "military_morale": state.military_morale, "court_prestige": state.court_prestige,
            })
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
        if state is not None and not _minister_exists(state, decree.target):
            return "任免目标人物不存在"
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
            elif decree.sub_action == PersonnelAction.EXECUTE and m.status != MinisterStatus.REMOVED:
                m.status = MinisterStatus.REMOVED
                executed.add(m.name)
            elif decree.sub_action == PersonnelAction.APPOINT and m.status == MinisterStatus.IDLE:
                m.status = MinisterStatus.ACTIVE
            break
    return dismissed, executed


# ── Passive Drift ────────────────────────────────────────

def apply_passive_drift(state: GameState, attr: dict) -> None:
    for r in state.regions:
        if r.threat != RegionThreat.NONE:
            r.stability -= 3
            r.civil_morale -= 2
            r.disaster_level += 3
            _attr_add(attr, f"{r.name}_stability", "passive_drift", -3)
            _attr_add(attr, f"{r.name}_civil_morale", "passive_drift", -2)
            _attr_add(attr, f"{r.name}_disaster_level", "passive_drift", 3)
        if r.stability < 30:
            r.rebellion_risk += 2
            r.tax_rate -= 0.02
            _attr_add(attr, f"{r.name}_rebellion_risk", "passive_drift", 2)
            _attr_add(attr, f"{r.name}_tax_rate", "passive_drift", -0.02)
        if r.civil_morale < 30:
            r.rebellion_risk += 1
            _attr_add(attr, f"{r.name}_rebellion_risk", "passive_drift", 1)
    if state.treasury < 50:
        state.military_morale -= 1
        _attr_add(attr, "military_morale", "passive_drift", -1)
    if any(r.stability < 20 for r in state.regions):
        state.civil_morale -= 2
        _attr_add(attr, "civil_morale", "passive_drift", -2)
    if any(f.rebellion_risk > 60 for f in state.factions):
        state.court_prestige -= 1
        _attr_add(attr, "court_prestige", "passive_drift", -1)
    # loyalty passive decay
    for m in state.ministers:
        m.loyalty -= 1
        _attr_add(attr, f"{m.name}_loyalty", "passive_drift", -1)
    # 怠政惩罚: pending/deferred memorials > 5
    pending_count = sum(
        1 for mem in state.memorials
        if mem.status in {MemorialStatus.PENDING, MemorialStatus.DEFERRED}
    )
    if pending_count > 5:
        state.court_prestige -= 3
        _attr_add(attr, "court_prestige", "passive_drift", -3)


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
                m.loyalty -= 20
                _attr_add(attr, f"{m.name}_loyalty", "loyalty_modification", -20)
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
                delta += 15
            elif decree.sub_action == PersonnelAction.DISMISS:
                delta -= 20
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
    for r in state.regions:
        if dt == DecreeType.TAX_INCREASE:
            if r.stability < 30:
                penalty = -15
            elif r.stability < 60:
                penalty = -8
            else:
                penalty = -5
            r.stability += penalty
            r.civil_morale -= 3
            r.rebellion_risk += 2
            _attr_add(attr, f"{r.name}_stability", "region_impact", penalty)
            _attr_add(attr, f"{r.name}_civil_morale", "region_impact", -3)
            _attr_add(attr, f"{r.name}_rebellion_risk", "region_impact", 2)
            tax_mod = 1.15
        elif dt == DecreeType.TAX_DECREASE:
            r.stability += 3
            r.civil_morale += 2
            r.rebellion_risk -= 1
            _attr_add(attr, f"{r.name}_stability", "region_impact", 3)
            _attr_add(attr, f"{r.name}_civil_morale", "region_impact", 2)
            _attr_add(attr, f"{r.name}_rebellion_risk", "region_impact", -1)
            tax_mod = 0.85
        elif dt == DecreeType.RECRUIT_TROOPS:
            if r.threat != RegionThreat.NONE:
                r.stability += 5
                r.garrison += 2000
                r.civil_morale -= 2
                _attr_add(attr, f"{r.name}_stability", "region_impact", 5)
                _attr_add(attr, f"{r.name}_garrison", "region_impact", 2000)
                _attr_add(attr, f"{r.name}_civil_morale", "region_impact", -2)
        elif dt == DecreeType.DISBAND_TROOPS:
            if r.garrison > 10000:
                r.garrison -= 3000
                _attr_add(attr, f"{r.name}_garrison", "region_impact", -3000)
        elif dt == DecreeType.DISASTER_RELIEF:
            if decree.target and r.name == decree.target:
                r.stability += 20
                r.civil_morale += 8
                r.disaster_level -= 15
                r.rebellion_risk -= 5
                _attr_add(attr, f"{r.name}_stability", "region_impact", 20)
                _attr_add(attr, f"{r.name}_civil_morale", "region_impact", 8)
                _attr_add(attr, f"{r.name}_disaster_level", "region_impact", -15)
                _attr_add(attr, f"{r.name}_rebellion_risk", "region_impact", -5)
        elif dt == DecreeType.HARSH_PUNISHMENT:
            if r.stability < 40:
                r.stability -= 8
                r.rebellion_risk -= 5
                _attr_add(attr, f"{r.name}_stability", "region_impact", -8)
                _attr_add(attr, f"{r.name}_rebellion_risk", "region_impact", -5)
            elif r.stability >= 60:
                r.stability += 3
                _attr_add(attr, f"{r.name}_stability", "region_impact", 3)
            r.civil_morale -= 4
            _attr_add(attr, f"{r.name}_civil_morale", "region_impact", -4)
    return tax_mod


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
        "apply": lambda s, a: _chain_apply(s, a, "流寇势力扩大", [
            ("陕西", "stability", -5), ("中原", "stability", -10),
            ("陕西", "rebellion_risk", 10), ("中原", "rebellion_risk", 5),
            ("陕西", "disaster_level", 10),
        ]),
    },
    {
        "name": "边军哗变",
        "check": lambda s: s.military_morale < 25 and s.treasury < 20,
        "apply": lambda s, a: _chain_apply(s, a, "边军哗变", [
            ("辽东", "stability", -20), ("辽东", "rebellion_risk", 15),
        ], faction_effects=[("边将势力", "rebellion_risk", 25)]),
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
        "apply": lambda s, a: _chain_apply(s, a, "后金入寇", [
            ("辽东", "stability", -20), ("京畿", "stability", -10),
            ("辽东", "disaster_level", 20), ("京畿", "disaster_level", 10),
        ], global_effects=[("military_morale", -15)]),
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
    r.civil_morale -= 10
    r.tax_rate -= 0.2
    _attr_add(attr, "江南_stability", "chain_event", -15)
    _attr_add(attr, "江南_civil_morale", "chain_event", -10)
    _attr_add(attr, "江南_tax_rate", "chain_event", -0.2)
    state.treasury += 10
    _attr_add(attr, "treasury", "chain_event", 10)


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
    supply_crisis = state.military_supply < 20
    if morale_crisis or supply_crisis:
        dev = 0
        if morale_crisis:
            dev += 25 - state.military_morale
        if supply_crisis:
            dev += 20 - state.military_supply
        urg = "critical" if morale_crisis and supply_crisis else "high"
        _add("military_crisis", "national",
             _pick_minister_by_ability(state, "military", faction="边将势力"),
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
        if current_months <= cooldown_until:
            continue
        if evt["check"](state):
            to_fire.append(evt)
    # apply phase
    triggered = []
    for evt in to_fire:
        evt["apply"](state, attr)
        triggered.append(evt["name"])
        state.event_cooldowns[evt["name"]] = current_months + 3
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


_BASE_TAX = {TaxContribution.LOW: 20, TaxContribution.MEDIUM: 35, TaxContribution.HIGH: 55}


def recalc_tax_collected(state: GameState, decree_tax_modifier: float) -> None:
    for r in state.regions:
        r.tax_rate = round(r.tax_rate, 2)
        base = _BASE_TAX[r.tax_contribution]
        stability_factor = r.stability / 100.0
        r.tax_collected = math.floor(base * r.tax_rate * stability_factor * decree_tax_modifier)


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
                loyalty_effects=[list(item) for item in c.loyalty_effects],
                state_effects=dict(c.state_effects),
            )
            for c in se.choices
        ],
        is_scripted=True,
        is_blocking=se.is_blocking,
        script_id=se.script_id,
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

        _attr_add(attr, attr_key, "ai_effects", value)

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
        attr.setdefault(attr_key, {})["ai_effects"] = value

        if category == "minister" and field == "status":
            if value == "removed":
                executed.add(name)
            elif value == "idle":
                dismissed.add(name)

    return dismissed, executed


def add_ai_new_events(state: GameState, new_events: list[dict]) -> None:
    """Validate and add AI-created events to active_events. Max 3 per turn."""
    if not isinstance(new_events, list):
        return
    added = 0
    for evt in new_events:
        if added >= 3:
            break
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


# ── Main Pipeline ────────────────────────────────────────

def process_decree(
    state: GameState,
    decree: StructuredDecree | None = None,
    freeform: FreeformResult | None = None,
) -> tuple[dict, dict, list[str], dict | None, list[MinisterReaction], TurnSummary]:
    """Returns (delta, attribution, triggered_events, game_over, minister_reactions, turn_summary).
    decree=None and freeform=None means a 'wait' turn (passive drift + time advance only).
    """
    attr: dict = {}
    reactions: list[MinisterReaction] = []

    # snapshot before passive_drift (for turn summary)
    before_snapshot = state.model_dump()

    # 1. passive drift
    apply_passive_drift(state, attr)

    decree_tax_modifier = 1.0

    if freeform is not None:
        # ── Freeform branch ──
        # validate + apply AI effects
        valid_effects = validate_ai_effects(freeform.effects, state)
        dismissed, executed = apply_ai_effects(state, valid_effects, attr)

        # execution backlash (same logic as structured path)
        for name in executed:
            target_m = next((m for m in state.ministers if m.name == name), None)
            if target_m:
                for f in state.factions:
                    if f.name == target_m.faction:
                        f.satisfaction -= 15
                        f.rebellion_risk += 10
                        _attr_add(attr, f"{f.name}_satisfaction", "execution_backlash", -15)
                        _attr_add(attr, f"{f.name}_rebellion_risk", "execution_backlash", 10)

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
                        f.satisfaction -= 15
                        f.rebellion_risk += 10
                        _attr_add(attr, f"{f.name}_satisfaction", "execution_backlash", -15)
                        _attr_add(attr, f"{f.name}_rebellion_risk", "execution_backlash", 10)
        # 3.6 loyalty modification
        apply_loyalty_modification(state, decree, attr, dismissed)
        # 3.7 minister reactions
        reactions = generate_minister_reactions(state, decree, attr)
        # 4. region impact
        decree_tax_modifier = apply_region_impact(state, decree, attr)

    # ── Merge point: shared pipeline ──
    # 5. chain events
    triggered = detect_chain_events(state, attr)
    # 5.5 tax recalculation
    recalc_tax_collected(state, decree_tax_modifier)
    # 6. clamp
    clamp_state(state)
    # after_snapshot for turn summary (post-clamp, pre-time_advance)
    after_snapshot = state.model_dump()
    # 6.5 memorial triggers (post-clamp)
    triggered_memorials = detect_memorial_triggers(state, attr)
    if triggered_memorials:
        state.memorials.extend(triggered_memorials)
    # region control
    update_region_control(state)
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
    # time
    advance_time(state)
    state.decree_count += 1
    # script events after time advance
    script_triggered = inject_script_events(state)
    triggered.extend(script_triggered)
    # game end
    game_over = check_game_end(state)
    # delta (full before/after including time advance)
    after = state.model_dump()
    delta = _compute_delta(before_snapshot, after)
    # turn summary (uses pre-time_advance snapshots per D17)
    summary = generate_turn_summary(
        before_snapshot,
        after_snapshot,
        triggered,
        reactions,
        state,
        decree=decree,
        freeform=freeform,
    )

    return delta, attr, triggered, game_over, reactions, summary


def _validate_freeform_reactions(
    raw_reactions: list[MinisterReaction], state: GameState,
) -> list[MinisterReaction]:
    """Validate AI-provided reactions: drop invalid minister refs, fill defaults."""
    active_names = {
        m.name: m for m in state.ministers
        if m.status != MinisterStatus.REMOVED
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

_GLOBAL_INDICATORS = ("treasury", "population", "military_supply", "civil_morale", "military_morale", "court_prestige")
_PENDING_STATUSES = {MemorialStatus.PENDING.value, MemorialStatus.DEFERRED.value}
_INDICATOR_LABELS = {
    "treasury": "国库",
    "population": "人口",
    "military_supply": "军备",
    "civil_morale": "民心",
    "military_morale": "军心",
    "court_prestige": "朝廷威望",
}
_MINISTER_STATUS_LABELS = {
    "active": "在朝",
    "idle": "闲置",
    "removed": "革除",
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


def generate_turn_summary(
    before: dict, after: dict,
    triggered: list[str], reactions: list[MinisterReaction],
    state: GameState,
    decree: StructuredDecree | None = None,
    freeform: FreeformResult | None = None,
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
        if br["stability"] != ar["stability"] or br["control"] != ar["control"] or br["threat"] != ar["threat"]:
            region_changes.append(RegionChange(
                name=ar["name"],
                stability_before=br["stability"], stability_after=ar["stability"],
                control_before=br["control"], control_after=ar["control"],
                threat_before=br["threat"], threat_after=ar["threat"],
            ))

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
        pending_memorials_count=pending_count,
    )


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
        for field in ("stability", "garrison", "civil_morale", "rebellion_risk", "tax_collected", "disaster_level"):
            d = ar[field] - br[field]
            if d != 0:
                delta[f"{name}_{field}"] = d
        tax_d = ar["tax_rate"] - br["tax_rate"]
        if abs(tax_d) > 1e-9:
            delta[f"{name}_tax_rate"] = round(tax_d, 4)
    return delta
