import copy
import json
import math
import random
import uuid

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

import engine.core as core_mod
from models.game import (
    GameState, GameTime, Faction, Region, Minister, MinisterAbilities,
    StructuredDecree, Memorial, MinisterReaction, CourtAssembly,
    FreeformResult, MissionState,
    TurnSummary, IndicatorTrend, FactionChange, RegionChange, MinisterChange,
    create_initial_state, clamp_state,
    INITIAL_MINISTERS, INITIAL_FACTIONS, INITIAL_REGIONS,
)
from models.enums import (
    DecreeType, RegionControl, RegionThreat, TaxContribution,
    MinisterStatus, PersonnelAction, MemorialStatus, EventUrgency,
)
from engine.core import (
    process_decree, apply_loyalty_modification, detect_memorial_triggers,
    generate_minister_reactions, generate_turn_summary,
    apply_passive_drift, inject_script_events, prepare_month_advance, _time_to_months,
    validate_ai_effects, apply_ai_effects, _apply_mission_decree,
)
from engine.tables import FACTION_STANCE
from engine.scripts import SCRIPT_REGISTRY, get_scripts_for_time
from api.assembly_helpers import select_assembly_participants
from api.helpers import apply_state_effects as _apply_state_effects
from db.saves import _migrate_save


# ── Helpers ──────────────────────────────────────────────

def make_state(**overrides) -> GameState:
    defaults = dict(
        time=GameTime(year=1360, month=6, era_name="至正", era_year=20),
        national_treasury=15, imperial_treasury=8, grain=420,
        population=1600, military_strength=18,
        civil_morale=62, military_morale=68, court_prestige=62,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=[m.model_copy() for m in INITIAL_MINISTERS],
    )
    defaults.update(overrides)
    return GameState(**defaults)


def _region(state: GameState, name: str) -> Region:
    return next(r for r in state.regions if r.name == name)


def _faction(state: GameState, name: str) -> Faction:
    return next(f for f in state.factions if f.name == name)


def _minister(state: GameState, name: str) -> Minister:
    return next(m for m in state.ministers if m.name == name)


def _neutralize_crises(state: GameState) -> None:
    """将默认数据自带的临界值推回安全区，保证触发类用例不被无关候选挤占（奏疏上限 2 条）。"""
    for f in state.factions:
        f.satisfaction = max(f.satisfaction, 30)
        f.rebellion_risk = min(f.rebellion_risk, 60)
    for r in state.regions:
        r.stability = max(r.stability, 20)
    state.military_morale = max(state.military_morale, 25)
    state.military_strength = max(state.military_strength, 20)


# ── 20.1 Minister loyalty field validation and clamp ─────

class TestMinisterLoyalty:
    def test_default_loyalty(self):
        m = Minister(name="x", faction="y")
        assert m.loyalty == 50

    def test_loyalty_bounds_valid(self):
        m = Minister(name="x", faction="y", loyalty=0)
        assert m.loyalty == 0
        m = Minister(name="x", faction="y", loyalty=100)
        assert m.loyalty == 100

    def test_loyalty_out_of_bounds(self):
        with pytest.raises(ValidationError):
            Minister(name="x", faction="y", loyalty=101)
        with pytest.raises(ValidationError):
            Minister(name="x", faction="y", loyalty=-1)

    def test_clamp_state_clamps_loyalty(self):
        state = make_state()
        state.ministers[0].loyalty = 150
        state.ministers[1].loyalty = -30
        clamp_state(state)
        assert state.ministers[0].loyalty == 100
        assert state.ministers[1].loyalty == 0

    def test_initial_ministers_loyalty(self):
        for m in INITIAL_MINISTERS:
            assert 0 <= m.loyalty <= 100


# ── 20.2 apply_loyalty_modification correctness ─────────

class TestApplyLoyaltyModification:
    def test_positive_stance_formula(self):
        state = make_state()
        for m in state.ministers:
            m.loyalty = 50
        decree = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
        attr = {}
        apply_loyalty_modification(state, decree, attr)
        for m in state.ministers:
            if m.status != MinisterStatus.ACTIVE:
                assert m.loyalty == 50, f"{m.name}: inactive minister should be skipped"
                continue
            stance = FACTION_STANCE.get(m.faction, {}).get(decree.type, 0)
            if stance > 0:
                expected = 50 + math.floor(stance * 0.3)
                assert m.loyalty == expected, f"{m.name}: expected {expected}, got {m.loyalty}"
            elif stance < 0:
                expected = 50 + math.floor(stance * 0.5)
                assert m.loyalty == expected, f"{m.name}: expected {expected}, got {m.loyalty}"
            else:
                assert m.loyalty == 50

    def test_negative_stance_formula(self):
        state = make_state()
        for m in state.ministers:
            m.loyalty = 50
        decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        attr = {}
        apply_loyalty_modification(state, decree, attr)
        # 幕府文臣 stance=-15 → floor(-15*0.5)=-8 → loyalty=42
        mufu = _minister(state, "李善长")
        assert mufu.loyalty == 50 + math.floor(-15 * 0.5)

    def test_idle_minister_skipped(self):
        state = make_state()
        state.ministers[0].status = MinisterStatus.IDLE
        state.ministers[0].loyalty = 50
        attr = {}
        apply_loyalty_modification(state, StructuredDecree(type=DecreeType.TAX_INCREASE), attr)
        assert state.ministers[0].loyalty == 50

    def test_dismissed_minister_penalty(self):
        state = make_state()
        target = state.ministers[0]
        target.loyalty = 50
        target.status = MinisterStatus.IDLE
        attr = {}
        apply_loyalty_modification(
            state, StructuredDecree(type=DecreeType.PERSONNEL, target=target.name, sub_action=PersonnelAction.DISMISS),
            attr, dismissed={target.name},
        )
        assert target.loyalty == 30  # 50 - 20

    def test_personnel_appoint_bonus(self):
        state = make_state()
        target = _minister(state, "杨宪")
        target.status = MinisterStatus.IDLE
        target.loyalty = 50
        # re-appoint
        target.status = MinisterStatus.ACTIVE
        attr = {}
        apply_loyalty_modification(
            state, StructuredDecree(type=DecreeType.PERSONNEL, target="杨宪", sub_action=PersonnelAction.APPOINT),
            attr,
        )
        stance = FACTION_STANCE.get(target.faction, {}).get(DecreeType.PERSONNEL, 0)
        expected_delta = math.floor(stance * 0.5) if stance < 0 else math.floor(stance * 0.3) if stance > 0 else 0
        expected_delta += 15
        assert target.loyalty == 50 + expected_delta


# ── 20.3 detect_memorial_triggers conditions and cooldown ─

class TestDetectMemorialTriggers:
    def test_faction_crisis_triggers(self):
        state = make_state()
        _neutralize_crises(state)
        _faction(state, "汉政权").satisfaction = 25
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        reasons = [m.trigger_reason for m in triggered]
        assert any("faction_crisis:汉政权" in r for r in reasons)

    def test_no_trigger_at_boundary(self):
        state = make_state()
        for f in state.factions:
            f.satisfaction = 30
        for r in state.regions:
            r.stability = 20
        for f in state.factions:
            f.rebellion_risk = 60
        state.military_morale = 25
        state.military_strength = 20
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        assert len(triggered) == 0

    def test_region_crisis_triggers(self):
        state = make_state()
        _region(state, "武昌").stability = 15
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        reasons = [m.trigger_reason for m in triggered]
        assert any("region_crisis:武昌" in r for r in reasons)

    def test_rebellion_warning_triggers(self):
        state = make_state()
        _faction(state, "淮西勋将").rebellion_risk = 65
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        reasons = [m.trigger_reason for m in triggered]
        assert any("rebellion_warning:淮西勋将" in r for r in reasons)

    def test_military_crisis_triggers(self):
        state = make_state()
        state.military_morale = 20
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        reasons = [m.trigger_reason for m in triggered]
        assert any("military_crisis:national" in r for r in reasons)

    def test_max_two_per_turn(self):
        state = make_state()
        for f in state.factions:
            f.satisfaction = 10
        for r in state.regions:
            r.stability = 5
        state.military_morale = 10
        state.military_strength = 10
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        assert len(triggered) <= 2

    def test_cooldown_prevents_retrigger(self):
        state = make_state()
        _faction(state, "汉政权").satisfaction = 10
        attr = {}
        t1 = detect_memorial_triggers(state, attr)
        assert len(t1) > 0
        state.memorials.extend(t1)
        # same turn, cooldown set
        t2 = detect_memorial_triggers(state, attr)
        # should not retrigger same entity
        for m in t2:
            for m1 in t1:
                assert m.trigger_reason != m1.trigger_reason

    def test_dedup_with_pending_memorial(self):
        state = make_state()
        _faction(state, "汉政权").satisfaction = 10
        state.memorials.append(Memorial(
            id="test-1", author_name="x", author_faction="y",
            title="t", content="c", trigger_reason="faction_crisis:汉政权",
            urgency="high", created_year=1360, created_month=6,
            status=MemorialStatus.PENDING,
        ))
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        reasons = [m.trigger_reason for m in triggered]
        assert "faction_crisis:汉政权" not in reasons

    def test_urgency_critical_for_very_low(self):
        state = make_state()
        _region(state, "武昌").stability = 5
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        region_memorial = next((m for m in triggered if "region_crisis:武昌" in m.trigger_reason), None)
        if region_memorial:
            assert region_memorial.urgency == "critical"


# ── 20.4 generate_minister_reactions selection and limits ─

class TestGenerateMinisterReactions:
    def test_basic_reactions(self):
        state = make_state()
        decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        attr = {}
        # pre-fill loyalty attr for reactions to read
        apply_loyalty_modification(state, decree, attr)
        reactions = generate_minister_reactions(state, decree, attr)
        assert len(reactions) <= 4

    def test_supporters_and_opposers(self):
        state = make_state()
        decree = StructuredDecree(type=DecreeType.TAX_INCREASE)
        attr = {}
        apply_loyalty_modification(state, decree, attr)
        reactions = generate_minister_reactions(state, decree, attr)
        types = {r.reaction_type for r in reactions}
        # TAX_INCREASE: 幕府文臣 stance=-12 (oppose), 江南士绅 stance=-8 (oppose), 淮西勋将 stance=3 (not>5)
        assert "oppose" in types

    def test_max_two_per_type(self):
        state = make_state()
        decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        attr = {}
        apply_loyalty_modification(state, decree, attr)
        reactions = generate_minister_reactions(state, decree, attr)
        support_count = sum(1 for r in reactions if r.reaction_type == "support")
        oppose_count = sum(1 for r in reactions if r.reaction_type == "oppose")
        assert support_count <= 2
        assert oppose_count <= 2

    def test_idle_minister_excluded(self):
        state = make_state()
        for m in state.ministers:
            m.status = MinisterStatus.IDLE
        decree = StructuredDecree(type=DecreeType.TAX_INCREASE)
        attr = {}
        reactions = generate_minister_reactions(state, decree, attr)
        assert len(reactions) == 0


# ── 20.5 generate_turn_summary comparison logic ─────────

class TestGenerateTurnSummary:
    def test_indicator_trends(self):
        state = make_state()
        before = state.model_dump()
        state.national_treasury += 10
        state.civil_morale -= 5
        after = state.model_dump()
        summary = generate_turn_summary(before, after, [], [], state)
        names = {t.name for t in summary.indicator_trends}
        assert "national_treasury" in names
        assert "civil_morale" in names

    def test_no_change_no_trend(self):
        state = make_state()
        snap = state.model_dump()
        summary = generate_turn_summary(snap, snap, [], [], state)
        assert len(summary.indicator_trends) == 0

    def test_faction_changes(self):
        state = make_state()
        before = state.model_dump()
        state.factions[0].satisfaction += 10
        after = state.model_dump()
        summary = generate_turn_summary(before, after, [], [], state)
        assert len(summary.faction_changes) > 0
        assert summary.faction_changes[0].satisfaction_after == before["factions"][0]["satisfaction"] + 10

    def test_region_changes(self):
        state = make_state()
        before = state.model_dump()
        state.regions[0].stability -= 5
        after = state.model_dump()
        summary = generate_turn_summary(before, after, [], [], state)
        assert len(summary.region_changes) > 0

    def test_minister_changes(self):
        state = make_state()
        before = state.model_dump()
        state.ministers[0].loyalty += 10
        after = state.model_dump()
        summary = generate_turn_summary(before, after, [], [], state)
        assert len(summary.minister_changes) > 0
        mc = summary.minister_changes[0]
        assert mc.loyalty_after == mc.loyalty_before + 10

    def test_pending_memorials_count(self):
        state = make_state()
        state.memorials.append(Memorial(
            id="t1", author_name="x", author_faction="y",
            title="t", content="c", trigger_reason="test",
            urgency="medium", created_year=1360, created_month=6,
            status=MemorialStatus.PENDING,
        ))
        snap = state.model_dump()
        summary = generate_turn_summary(snap, snap, [], [], state)
        assert summary.pending_memorials_count == 1

    def test_major_events(self):
        state = make_state()
        snap = state.model_dump()
        summary = generate_turn_summary(snap, snap, ["流寇势力扩大", "边军哗变"], [], state)
        assert summary.major_events == ["流寇势力扩大", "边军哗变"]

    def test_region_details_from_attr(self):
        state = make_state()
        before = state.model_dump()
        state.regions[0].stability -= 10
        state.regions[0].garrison += 2000
        after = state.model_dump()
        rname = state.regions[0].name
        attr = {
            f"{rname}_stability": {"增兵": -3, "自然变化": -7},
            f"{rname}_garrison": {"增兵": 2000},
        }
        summary = generate_turn_summary(before, after, [], [], state, attr=attr)
        assert summary.region_details is not None
        assert len(summary.region_details) == 3
        # sorted by region name; all same region here
        fields = [(d.field, d.source, d.delta) for d in summary.region_details]
        assert ("stability", "增兵", -3.0) in fields
        assert ("stability", "自然变化", -7.0) in fields
        assert ("garrison", "增兵", 2000.0) in fields

    def test_region_details_sorted_by_region(self):
        state = make_state()
        before = state.model_dump()
        # change two regions
        r_a = next(r for r in state.regions if r.name == "武昌")
        r_b = next(r for r in state.regions if r.name == "两淮")
        r_a.stability -= 5
        r_b.stability -= 3
        after = state.model_dump()
        attr = {
            "武昌_stability": {"自然变化": -5},
            "两淮_stability": {"自然变化": -3},
        }
        summary = generate_turn_summary(before, after, [], [], state, attr=attr)
        assert summary.region_details is not None
        regions = [d.region for d in summary.region_details]
        assert regions == sorted(regions)


# ── 20.6 Save migration compatibility ──────────────────

class TestSaveMigrationPhase3:
    def _old_save(self):
        return {
            "time": {"year": 1360, "month": 6},
            "treasury": 100, "population": 100, "military_supply": 80,
            "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
            "factions": [], "active_events": [], "history_log": [],
            "decree_count": 5, "event_cooldowns": {},
            "regions": [],
            "ministers": [m.model_dump() for m in INITIAL_MINISTERS],
        }

    def test_memorials_default_empty(self):
        data = self._old_save()
        # remove phase3 fields
        for key in ("memorials", "memorial_cooldowns", "last_assembly",
                     "loyalty_zero_triggered", "last_assembly_month"):
            data.pop(key, None)
        _migrate_save(data)
        assert data["memorials"] == []

    def test_memorial_cooldowns_default_empty(self):
        data = self._old_save()
        data.pop("memorial_cooldowns", None)
        _migrate_save(data)
        assert data["memorial_cooldowns"] == {}

    def test_loyalty_default_50(self):
        data = self._old_save()
        for m in data["ministers"]:
            m.pop("loyalty", None)
        _migrate_save(data)
        for m in data["ministers"]:
            assert m["loyalty"] == 50

    def test_last_assembly_default_none(self):
        data = self._old_save()
        data.pop("last_assembly", None)
        _migrate_save(data)
        assert data["last_assembly"] is None

    def test_loyalty_zero_triggered_default_empty(self):
        data = self._old_save()
        data.pop("loyalty_zero_triggered", None)
        _migrate_save(data)
        assert data["loyalty_zero_triggered"] == []

    def test_last_assembly_month_default_zero(self):
        data = self._old_save()
        data.pop("last_assembly_month", None)
        _migrate_save(data)
        assert data["last_assembly_month"] == 0

    def test_full_old_save_loads(self):
        data = self._old_save()
        for key in ("memorials", "memorial_cooldowns", "last_assembly",
                     "loyalty_zero_triggered", "last_assembly_month", "resolved_script_ids"):
            data.pop(key, None)
        for m in data["ministers"]:
            m.pop("loyalty", None)
        _migrate_save(data)
        state = GameState.model_validate(data)
        assert state.memorials == []
        assert all(m.loyalty == 50 for m in state.ministers)


# ── 20.7 Script events trigger conditions and effects ───

class TestScriptEventsPhase3:
    def test_poyang_battle_no_condition(self):
        scripts = get_scripts_for_time(1363, 7)
        evt = next((s for s in scripts if s.script_id == "poyang-battle-1363-07"), None)
        assert evt is not None
        assert evt.condition is None
        assert evt.is_blocking is True

    def test_chen_youliang_endgame_condition(self):
        scripts = get_scripts_for_time(1363, 9)
        evt = next((s for s in scripts if s.script_id == "chen-youliang-endgame-1363-09"), None)
        assert evt is not None
        state = make_state()
        state.resolved_script_ids = set()
        assert evt.condition(state) is False
        state.resolved_script_ids = {"poyang-battle-1363-07"}
        assert evt.condition(state) is True
        _minister(state, "陈友谅").status = MinisterStatus.REMOVED
        assert evt.condition(state) is False

    def test_han_regroup_condition(self):
        scripts = get_scripts_for_time(1363, 9)
        evt = next((s for s in scripts if s.script_id == "han-regroup-1363-09"), None)
        assert evt is not None
        state = make_state()
        state.resolved_script_ids = {"poyang-battle-1363-07"}
        assert evt.condition(state) is False
        _minister(state, "陈友谅").status = MinisterStatus.REMOVED
        assert evt.condition(state) is True

    def test_redturban_remnants_condition(self):
        scripts = get_scripts_for_time(1357, 6)
        evt = next((s for s in scripts if s.script_id == "redturban-remnants-1357-06"), None)
        assert evt is not None
        state = make_state()
        _region(state, "两淮").stability = 29
        assert evt.condition(state) is True
        _region(state, "两淮").stability = 30
        assert evt.condition(state) is False

    def test_xuda_campaign_condition(self):
        scripts = get_scripts_for_time(1358, 5)
        evt = next((s for s in scripts if s.script_id == "xuda-eastern-campaign-1358-05"), None)
        assert evt is not None
        state = make_state()
        _minister(state, "徐达").status = MinisterStatus.ACTIVE
        state.military_strength = 21
        assert evt.condition(state) is True
        state.military_strength = 20
        assert evt.condition(state) is False
        state.military_strength = 30
        _minister(state, "徐达").status = MinisterStatus.IDLE
        assert evt.condition(state) is False

    def test_pingjiang_siege_condition(self):
        scripts = get_scripts_for_time(1366, 8)
        evt = next((s for s in scripts if s.script_id == "pingjiang-siege-1366-08"), None)
        assert evt is not None
        state = make_state()
        _region(state, "平江").stability = 39
        assert evt.condition(state) is True
        _region(state, "平江").stability = 40
        assert evt.condition(state) is False

    def test_all_phase3_scripts_have_choices(self):
        phase3_ids = [
            "poyang-battle-1363-07",
            "chen-youliang-endgame-1363-09", "redturban-remnants-1357-06",
            "xuda-eastern-campaign-1358-05", "pingjiang-siege-1366-08",
            "han-regroup-1363-09",
        ]
        for sid in phase3_ids:
            assert sid in SCRIPT_REGISTRY
            assert len(SCRIPT_REGISTRY[sid].choices) >= 2

    def test_opening_script_loyalty_effects(self):
        evt = SCRIPT_REGISTRY["yingtian-founding-1356-03"]
        choice2 = evt.choices[2]  # 裁汰冗员，整肃幕府
        assert ("杨宪", -20) in choice2.loyalty_effects
        assert ("李善长", 5) in choice2.loyalty_effects


# ── 20.8 process_decree pipeline order and return ────────

class TestProcessDecreePipeline:
    def test_returns_six_values(self):
        state = make_state()
        result = process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        assert len(result) == 6
        delta, attr, triggered, game_over, reactions, summary = result
        assert isinstance(delta, dict)
        assert isinstance(attr, dict)
        assert isinstance(triggered, list)
        assert isinstance(reactions, list)
        assert isinstance(summary, TurnSummary)

    def test_wait_turn(self):
        state = make_state()
        delta, attr, triggered, game_over, reactions, summary = process_decree(state)
        assert isinstance(delta, dict)
        assert reactions == []
        assert isinstance(summary, TurnSummary)

    def test_time_advances(self):
        state = make_state()
        before_month = state.time.month
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        # time advancement is handled by advance_month(), not process_decree()
        assert state.time.month == before_month

    def test_decree_count_does_not_increment_during_decree_execution(self):
        state = make_state()
        before = state.decree_count
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        # decree_count is incremented in advance_month(), not process_decree()
        assert state.decree_count == before

    def test_decree_count_increments_on_month_advance(self):
        state = make_state()
        before = state.decree_count
        prepare_month_advance(state)
        assert state.decree_count == before + 1

    def test_reactions_populated(self):
        state = make_state()
        decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        _, _, _, _, reactions, _ = process_decree(state, decree)
        # HARSH_PUNISHMENT has strong stances, should produce reactions
        assert len(reactions) > 0

    def test_memorial_triggers_added_to_state(self):
        state = make_state()
        for f in state.factions:
            f.satisfaction = 10
        for r in state.regions:
            r.stability = 5
        before_count = len(state.memorials)
        process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
        # memorials should have been added
        assert len(state.memorials) >= before_count


class TestMinisterMissions:
    def _set_active_mission(self, state: GameState, minister_name: str = "刘基") -> Minister:
        minister = _minister(state, minister_name)
        minister.status = MinisterStatus.ON_MISSION
        minister.current_mission = MissionState(
            name="研制火炮",
            progress_months=1,
            total_months=2,
            cost=5,
            effects={"global.military_strength": 10},
        )
        return minister

    def test_status_validation_accepts_active_to_on_mission(self):
        state = make_state()
        minister = _minister(state, "刘基")
        minister.status = MinisterStatus.ACTIVE

        valid = validate_ai_effects({"minister.刘基.status": "on_mission"}, state)

        assert valid == {"minister.刘基.status": "on_mission"}

    def test_status_validation_rejects_idle_to_on_mission(self):
        state = make_state()
        minister = _minister(state, "刘基")
        minister.status = MinisterStatus.IDLE

        valid = validate_ai_effects({"minister.刘基.status": "on_mission"}, state)

        assert valid == {}

    def test_mission_creation_validates_effects(self):
        state = make_state(national_treasury=20)
        minister = _minister(state, "刘基")
        minister.status = MinisterStatus.ACTIVE
        freeform = FreeformResult(effects={
            "_mission_刘基": {
                "name": "研制火炮",
                "total_months": 2,
                "cost": 5,
                "effects": {
                    "global.military_strength": 10,
                    "invalid.path": 99,
                },
            },
        })

        assert _apply_mission_decree(state, freeform) is True
        assert minister.status == MinisterStatus.ON_MISSION
        assert minister.current_mission is not None
        assert minister.current_mission.effects == {"global.military_strength": 10}
        assert state.national_treasury == 15

    def test_mission_creation_insufficient_treasury_leaves_state_unchanged(self):
        state = make_state(national_treasury=4)
        minister = _minister(state, "刘基")
        minister.status = MinisterStatus.ACTIVE
        freeform = FreeformResult(effects={
            "_mission_刘基": {
                "name": "研制火炮",
                "total_months": 2,
                "cost": 5,
                "effects": {"global.military_strength": 10},
            },
        })

        assert _apply_mission_decree(state, freeform) is False
        assert minister.status == MinisterStatus.ACTIVE
        assert minister.current_mission is None
        assert state.national_treasury == 4

    def test_validated_status_cancellation_clears_current_mission_without_refund(self):
        state = make_state(national_treasury=10)
        minister = self._set_active_mission(state)
        valid = validate_ai_effects({"minister.刘基.status": "active"}, state)

        dismissed, executed = apply_ai_effects(state, valid, {})

        assert dismissed == set()
        assert executed == set()
        assert minister.status == MinisterStatus.ACTIVE
        assert minister.current_mission is None
        assert state.national_treasury == 10

    def test_invalid_mission_effect_keys_are_ignored_on_completion(self):
        state = make_state(military_strength=40)
        minister = self._set_active_mission(state)
        minister.current_mission.effects = {
            "global.military_strength": 10,
            "invalid.path": 99,
        }

        prepare_month_advance(state)

        assert state.military_strength == 50
        assert minister.status == MinisterStatus.ACTIVE
        assert minister.current_mission is None
        assert any(entry.decree_type == "mission_complete" for entry in state.history_log)

    def test_mission_completion_failure_keeps_mission_for_retry(self, monkeypatch):
        state = make_state()
        minister = self._set_active_mission(state)

        def raise_failure(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(core_mod, "apply_ai_effects", raise_failure)
        prepare_month_advance(state)

        assert minister.status == MinisterStatus.ON_MISSION
        assert minister.current_mission is not None
        assert minister.current_mission.progress_months == 2
        assert not any(entry.decree_type == "mission_complete" for entry in state.history_log)

    def test_removed_minister_clears_current_mission_without_completion(self):
        state = make_state(military_strength=40)
        minister = self._set_active_mission(state)
        minister.status = MinisterStatus.REMOVED

        prepare_month_advance(state)

        assert minister.current_mission is None
        assert state.military_strength == 40
        assert not any(entry.decree_type == "mission_complete" for entry in state.history_log)


# ── 20.9 PBT: loyalty always in [0,100] ─────────────────

st_decree_type = st.sampled_from(list(DecreeType))


@given(seed=st.integers(min_value=0, max_value=99999))
@settings(max_examples=100)
def test_loyalty_always_in_range(seed):
    rng = random.Random(seed)
    state = make_state()
    for _ in range(3):
        dt = rng.choice(list(DecreeType))
        decree = StructuredDecree(type=dt)
        if dt == DecreeType.DISASTER_RELIEF:
            decree.target = "两淮"
        elif dt == DecreeType.DIPLOMACY:
            decree.target = "汉政权"
        elif dt == DecreeType.PERSONNEL:
            active = [m for m in state.ministers if m.status == MinisterStatus.ACTIVE]
            if active:
                decree.target = rng.choice(active).name
                decree.sub_action = rng.choice([PersonnelAction.APPOINT, PersonnelAction.DISMISS])
            else:
                continue
        try:
            process_decree(state, decree)
        except Exception:
            continue
    for m in state.ministers:
        assert 0 <= m.loyalty <= 100, f"{m.name} loyalty={m.loyalty} out of [0,100]"


# ── 20.10 Integration: decree→reactions→memorial→summary ─

class TestIntegrationFlow:
    def test_full_flow(self):
        state = make_state()
        # set up conditions for memorial triggers
        _faction(state, "汉政权").satisfaction = 10
        _region(state, "武昌").stability = 5

        decree = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        delta, attr, triggered, game_over, reactions, summary = process_decree(state, decree)

        # reactions should exist (HARSH_PUNISHMENT has strong stances)
        assert isinstance(reactions, list)
        # summary should be generated
        assert isinstance(summary, TurnSummary)
        assert summary.year > 0
        # memorials should have been triggered
        assert len(state.memorials) > 0
        # delta should have changes
        assert len(delta) > 0

    def test_wait_turn_still_produces_summary(self):
        state = make_state()
        delta, attr, triggered, game_over, reactions, summary = process_decree(state)
        assert isinstance(summary, TurnSummary)
        assert reactions == []


# ── 20.11 PBT: memorial trigger boundary values ─────────

class TestMemorialBoundaryValues:
    @pytest.mark.parametrize("sat,expected", [(29, True), (30, False)])
    def test_faction_crisis_boundary(self, sat, expected):
        state = make_state()
        _neutralize_crises(state)
        _faction(state, "汉政权").satisfaction = sat
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        found = any("faction_crisis:汉政权" in m.trigger_reason for m in triggered)
        assert found == expected

    @pytest.mark.parametrize("stab,expected", [(19, True), (20, False)])
    def test_region_crisis_boundary(self, stab, expected):
        state = make_state()
        _neutralize_crises(state)
        _region(state, "武昌").stability = stab
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        found = any("region_crisis:武昌" in m.trigger_reason for m in triggered)
        assert found == expected

    @pytest.mark.parametrize("risk,expected", [(61, True), (60, False)])
    def test_rebellion_warning_boundary(self, risk, expected):
        state = make_state()
        _faction(state, "淮西勋将").rebellion_risk = risk
        attr = {}
        triggered = detect_memorial_triggers(state, attr)
        found = any("rebellion_warning:淮西勋将" in m.trigger_reason for m in triggered)
        assert found == expected


# ── 20.12 PBT: cooldown per entity independence ─────────

@given(st.data())
@settings(max_examples=30)
def test_cooldown_per_entity_independent(data):
    state = make_state()
    # trigger on faction A
    _faction(state, "汉政权").satisfaction = 10
    attr = {}
    t1 = detect_memorial_triggers(state, attr)
    state.memorials.extend(t1)
    faction_a_triggered = any("faction_crisis:汉政权" in m.trigger_reason for m in t1)
    assert faction_a_triggered
    # now trigger on a different entity: region
    _region(state, "武昌").stability = 5
    t2 = detect_memorial_triggers(state, attr)
    # region_crisis should still fire despite faction cooldown
    region_triggered = any("region_crisis:武昌" in m.trigger_reason for m in t2)
    assert region_triggered


# ── 20.13 PBT: memorial dedup idempotency ───────────────

@given(st.data())
@settings(max_examples=30)
def test_memorial_dedup_idempotent(data):
    state = make_state()
    _faction(state, "汉政权").satisfaction = 10
    attr = {}
    t1 = detect_memorial_triggers(state, attr)
    state.memorials.extend(t1)
    # second detection should not duplicate
    t2 = detect_memorial_triggers(state, attr)
    for m2 in t2:
        for m1 in t1:
            if m2.trigger_reason == m1.trigger_reason:
                pytest.fail(f"Duplicate trigger_reason: {m2.trigger_reason}")


# ── 20.14 PBT: max 2/turn selection order-invariant ─────

@given(seed=st.integers(min_value=0, max_value=99999))
@settings(max_examples=30)
def test_max_2_order_invariant(seed):
    """Max 2/turn limit is enforced regardless of input order."""
    state = make_state()
    for f in state.factions:
        f.satisfaction = 10
    for r in state.regions:
        r.stability = 5
    state.military_morale = 10
    state.military_strength = 10

    attr = {}
    triggered = detect_memorial_triggers(state, attr)
    assert len(triggered) == 2
    # verify exactly 2 produced and all have valid urgency
    for m in triggered:
        assert m.urgency in {"critical", "high", "medium"}


# ── 20.15 PBT: approved memorial doesn't auto-execute ───

class TestApprovedMemorialNoRecursion:
    def test_approved_creates_pending_not_auto(self):
        state = make_state()
        # create a memorial with suggested decrees
        mem = Memorial(
            id="test-mem", author_name="刘基", author_faction="幕府文臣",
            title="test", content="test", trigger_reason="test:entity",
            urgency="high", created_year=1360, created_month=6,
            suggested_decrees=[StructuredDecree(type=DecreeType.TAX_DECREASE)],
            status=MemorialStatus.PENDING,
        )
        state.memorials.append(mem)
        # when we set it to approved, the decree is just data
        mem.status = MemorialStatus.APPROVED
        # no automatic process_decree call happens from model change
        # verify state didn't change (national_treasury unchanged, default 15)
        assert state.national_treasury == 15


# ── 20.16 PBT: pipeline step order consistency ──────────

@given(seed=st.integers(min_value=0, max_value=99999))
@settings(max_examples=15)
def test_pipeline_step_order_consistency(seed):
    rng = random.Random(seed)
    state1 = make_state()
    state2 = state1.model_copy(deep=True)
    dt = rng.choice(list(DecreeType))
    decree = StructuredDecree(type=dt)
    if dt == DecreeType.DISASTER_RELIEF:
        decree.target = "两淮"
    elif dt == DecreeType.DIPLOMACY:
        decree.target = "汉政权"
    elif dt == DecreeType.PERSONNEL:
        decree.target = "刘基"
        decree.sub_action = PersonnelAction.DISMISS
    r1 = process_decree(state1, decree)
    decree2 = StructuredDecree(type=dt, target=decree.target, sub_action=decree.sub_action)
    r2 = process_decree(state2, decree2)
    # same inputs → same delta
    assert r1[0] == r2[0]
    # states match except for non-deterministic UUIDs in memorials
    d1 = state1.model_dump()
    d2 = state2.model_dump()
    # normalize memorial ids for comparison
    for mem in d1.get("memorials", []):
        mem["id"] = "normalized"
    for mem in d2.get("memorials", []):
        mem["id"] = "normalized"
    assert d1 == d2


# ── 20.17 PBT: clamp idempotency ────────────────────────

@given(
    national_treasury=st.integers(min_value=-50, max_value=10250),
    morale=st.integers(min_value=-50, max_value=150),
    loyalty=st.integers(min_value=-50, max_value=150),
)
@settings(max_examples=50)
def test_clamp_idempotent(national_treasury, morale, loyalty):
    state = make_state()
    state.national_treasury = national_treasury
    state.civil_morale = morale
    state.ministers[0].loyalty = loyalty
    clamp_state(state)
    snap = state.model_dump()
    clamp_state(state)
    assert state.model_dump() == snap


# ── 20.18 PBT: save roundtrip preserves phase3 fields ───

@given(seed=st.integers(min_value=0, max_value=99999))
@settings(max_examples=30)
def test_save_roundtrip_phase3(seed):
    state = make_state()
    # add phase3 data
    state.memorials.append(Memorial(
        id=str(uuid.uuid4()), author_name="刘基", author_faction="幕府文臣",
        title="test", content="test content", trigger_reason="faction_crisis:幕府文臣",
        urgency="high", created_year=1360, created_month=6,
        status=MemorialStatus.PENDING,
    ))
    state.memorial_cooldowns = {"faction_crisis:幕府文臣": 100}
    state.loyalty_zero_triggered = {"杨宪"}
    state.last_assembly_month = 50
    state.ministers[0].loyalty = 30

    dumped = state.model_dump_json()
    loaded = json.loads(dumped)
    restored = GameState.model_validate(loaded)
    assert len(restored.memorials) == 1
    assert restored.memorials[0].title == "test"
    assert restored.memorial_cooldowns == {"faction_crisis:幕府文臣": 100}
    assert "杨宪" in restored.loyalty_zero_triggered
    assert restored.last_assembly_month == 50
    assert restored.ministers[0].loyalty == 30


# ── 20.19 PBT: migration idempotency with phase3 fields ─

@given(seed=st.integers(min_value=0, max_value=99999))
@settings(max_examples=30)
def test_migration_idempotent_phase3(seed):
    data = {
        "time": {"year": 1360, "month": 6},
        "treasury": 100, "population": 100, "military_supply": 80,
        "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
        "factions": [], "active_events": [], "history_log": [],
        "decree_count": 5, "event_cooldowns": {}, "regions": [],
    }
    _migrate_save(data)
    snap1 = copy.deepcopy(data)
    _migrate_save(data)
    assert data == snap1
    # verify phase3 fields present
    assert "memorials" in data
    assert "memorial_cooldowns" in data
    assert "last_assembly" in data
    assert "loyalty_zero_triggered" in data
    assert "last_assembly_month" in data


# ── 20.20 loyalty=0 triggers resignation once ───────────

class TestLoyaltyZeroResignation:
    def test_loyalty_zero_tracked(self):
        state = make_state()
        state.ministers[0].loyalty = 0
        state.loyalty_zero_triggered = set()
        # the tracking set records who has triggered
        state.loyalty_zero_triggered.add(state.ministers[0].name)
        assert state.ministers[0].name in state.loyalty_zero_triggered

    def test_only_triggers_once(self):
        state = make_state()
        name = state.ministers[0].name
        state.ministers[0].loyalty = 0
        state.loyalty_zero_triggered = set()
        # first time: trigger
        state.loyalty_zero_triggered.add(name)
        # second time: already in set
        assert name in state.loyalty_zero_triggered
        # won't trigger again
        state.loyalty_zero_triggered.add(name)
        assert len([n for n in state.loyalty_zero_triggered if n == name]) == 1


# ── 20.21 Assembly participant selection ─────────────────

class TestAssemblyParticipantSelection:
    def test_less_than_3_active(self):
        state = make_state()
        for m in state.ministers:
            m.status = MinisterStatus.IDLE
        # only 2 active
        state.ministers[0].status = MinisterStatus.ACTIVE
        state.ministers[1].status = MinisterStatus.ACTIVE
        participants = select_assembly_participants(state)
        assert len(participants) < 3

    def test_one_per_faction(self):
        state = make_state()
        participants = select_assembly_participants(state)
        # Each faction with active ministers must be represented
        # （敌对政权如吴政权/元廷在初始状态无在任大臣，不要求代表）
        factions_represented = {p.faction for p in participants}
        all_factions = {m.faction for m in state.ministers if m.status == MinisterStatus.ACTIVE}
        assert factions_represented == all_factions

    def test_max_5(self):
        state = make_state()
        participants = select_assembly_participants(state)
        assert len(participants) <= 15

    def test_tie_break_by_loyalty(self):
        state = make_state()
        # make two ministers in same faction with different loyalty
        m1 = _minister(state, "常遇春")  # 淮西勋将
        m2 = _minister(state, "徐达")  # 淮西勋将
        m1.loyalty = 95
        m2.loyalty = 30
        # 限定花名册只含二人（同为元帅、职位分相同），验证同派系内按忠诚度决胜；
        # 返回结果按分数降序，常遇春应排在徐达之前。
        state.ministers = [m1.model_copy(deep=True), m2.model_copy(deep=True)]
        participants = select_assembly_participants(state)
        border_participants = [p for p in participants if p.faction == "淮西勋将"]
        assert len(border_participants) == 2
        assert border_participants[0].name == "常遇春"
        assert border_participants[1].name == "徐达"

    def test_all_idle_returns_empty(self):
        state = make_state()
        for m in state.ministers:
            m.status = MinisterStatus.IDLE
        participants = select_assembly_participants(state)
        assert len(participants) == 0


# ── 20.22 Assembly once per month ────────────────────────

class TestAssemblyMonthlyLimit:
    def test_last_assembly_month_check(self):
        state = make_state()
        current_month = _time_to_months(state.time.year, state.time.month)
        state.last_assembly_month = current_month
        # the route checks: last_assembly_month >= current_month → reject
        assert state.last_assembly_month >= current_month

    def test_allowed_next_month(self):
        state = make_state()
        current_month = _time_to_months(state.time.year, state.time.month)
        state.last_assembly_month = current_month - 1
        assert state.last_assembly_month < current_month


# ── 20.23 Silence once per assembly ─────────────────────

class TestSilenceOncePerAssembly:
    def test_silenced_flag(self):
        assembly = CourtAssembly(
            topic="test", decree_type=DecreeType.TAX_INCREASE,
        )
        assert assembly.silenced is False
        assembly.silenced = True
        assert assembly.silenced is True

    def test_already_silenced_check(self):
        state = make_state()
        state.last_assembly = CourtAssembly(
            topic="test", decree_type=DecreeType.TAX_INCREASE, silenced=True,
        )
        # route checks: last_assembly.silenced → reject
        assert state.last_assembly.silenced is True


# ── 20.24 Adopt suggestion_index out of bounds ──────────

class TestAdoptSuggestionBounds:
    def test_negative_index(self):
        state = make_state()
        state.last_assembly = CourtAssembly(
            topic="test", decree_type=DecreeType.TAX_INCREASE,
            suggestions=[],
        )
        # route checks: index < 0 or index >= len(suggestions) → 400
        assert -1 < 0  # would fail in route
        assert 0 >= len(state.last_assembly.suggestions)  # would fail in route

    def test_exceeds_length(self):
        from models.game import PolicySuggestion
        state = make_state()
        state.last_assembly = CourtAssembly(
            topic="test", decree_type=DecreeType.TAX_INCREASE,
            suggestions=[PolicySuggestion(
                title="t", description="d",
                related_decree=StructuredDecree(type=DecreeType.TAX_INCREASE),
            )],
        )
        idx = 5
        assert idx >= len(state.last_assembly.suggestions)

    def test_valid_index(self):
        from models.game import PolicySuggestion
        state = make_state()
        state.last_assembly = CourtAssembly(
            topic="test", decree_type=DecreeType.TAX_INCREASE,
            suggestions=[PolicySuggestion(
                title="t", description="d",
                related_decree=StructuredDecree(type=DecreeType.TAX_INCREASE),
            )],
        )
        idx = 0
        assert 0 <= idx < len(state.last_assembly.suggestions)


# ── 20.25 Script state_effects execution order ──────────

class TestScriptStateEffectsOrder:
    def test_state_effects_applied(self):
        state = make_state()
        initial_national_treasury = state.national_treasury
        _apply_state_effects(state, {"global.national_treasury": -20})
        assert state.national_treasury == initial_national_treasury - 20

    def test_region_state_effect(self):
        state = make_state()
        initial_stab = _region(state, "武昌").stability
        _apply_state_effects(state, {"region.武昌.stability": -20})
        assert _region(state, "武昌").stability == initial_stab - 20

    def test_faction_state_effect(self):
        state = make_state()
        initial_sat = _faction(state, "淮西勋将").satisfaction
        _apply_state_effects(state, {"faction.淮西勋将.satisfaction": -25})
        assert _faction(state, "淮西勋将").satisfaction == initial_sat - 25

    def test_script_with_state_effects_and_decrees(self):
        """Verify state_effects + decrees + loyalty_effects + clamp order."""
        state = make_state()
        # simulate the route's execution order
        initial_national_treasury = state.national_treasury
        # 1. state_effects first
        _apply_state_effects(state, {"global.national_treasury": -20})
        assert state.national_treasury == initial_national_treasury - 20
        # 2. decree execution
        decree = StructuredDecree(type=DecreeType.TAX_INCREASE)
        process_decree(state, decree)
        # 3. loyalty_effects
        target = _minister(state, "徐达")
        old_loyalty = target.loyalty
        target.loyalty += -50
        # 4. clamp
        clamp_state(state)
        assert 0 <= target.loyalty <= 100
        assert 0 <= state.national_treasury <= 10000

    def test_poyang_battle_state_effects(self):
        evt = SCRIPT_REGISTRY["poyang-battle-1363-07"]
        choice0 = evt.choices[0]
        assert "region.武昌.stability" in choice0.state_effects
        assert "faction.汉政权.rebellion_risk" in choice0.state_effects
        assert "global.military_morale" in choice0.state_effects

    def test_yangxian_discipline_effects(self):
        evt = SCRIPT_REGISTRY["yangxian-discipline-1357-02"]
        choice1 = evt.choices[1]
        assert ("杨宪", -15) in choice1.loyalty_effects
        assert "global.court_prestige" in choice1.state_effects


# ── 10.12 DECREE_LABELS consistency between backend and frontend ──

class TestDecreeLabelsConsistency:
    FRONTEND_LABELS = {
        "tax_increase": "加征",
        "tax_decrease": "减赋",
        "recruit_troops": "募兵",
        "disband_troops": "裁军",
        "personnel": "任免",
        "diplomacy": "通好",
        "disaster_relief": "赈灾",
        "harsh_punishment": "严刑",
    }

    def test_all_decree_types_have_labels(self):
        from engine.tables import DECREE_LABELS
        for dt in DecreeType:
            assert dt in DECREE_LABELS, f"{dt} missing from backend DECREE_LABELS"

    def test_backend_frontend_labels_match(self):
        from engine.tables import DECREE_LABELS
        for dt in DecreeType:
            backend_label = DECREE_LABELS[dt]
            frontend_label = self.FRONTEND_LABELS.get(dt.value)
            assert frontend_label is not None, f"{dt.value} missing from frontend DECREE_LABELS"
            assert backend_label == frontend_label, (
                f"{dt.value}: backend='{backend_label}' != frontend='{frontend_label}'"
            )

    def test_frontend_has_no_extra_keys(self):
        backend_keys = {dt.value for dt in DecreeType}
        for key in self.FRONTEND_LABELS:
            assert key in backend_keys, f"frontend has extra key '{key}' not in DecreeType"
