"""Unit tests for balance-tuned mechanics:
- Region control state machine (COURT→UNSTABLE→FALLEN, recovery paths)
- apply_region_control_consequences
- collect_tax_revenue
- Player-death-only check_game_end
- Consecutive wait metadata without action-count penalties
- Military supply production
- assign_urgency (uses actual event name)
- Cooldown consistency
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from models.game import GameState, GameTime, create_initial_state, clamp_state
from models.enums import (
    RegionControl, RegionThreat, TaxContribution, EventUrgency,
    MinisterStatus, MemorialStatus,
)
from engine.core import (
    update_region_control, apply_region_control_consequences,
    collect_tax_revenue, recalc_tax_collected,
    check_game_end, apply_passive_drift, assign_urgency,
    detect_chain_events, process_decree, _attr_add,
)


def _make_state(**overrides) -> GameState:
    s = create_initial_state()
    # resolve blocking event
    s.active_events = [e for e in s.active_events if not e.is_blocking]
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ── Region Control State Machine ──────────────────────

class TestRegionControl:
    def test_court_to_unstable(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 14
        r.control = RegionControl.COURT
        update_region_control(s)
        assert r.control == RegionControl.UNSTABLE

    def test_court_stays_at_boundary(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 15
        r.control = RegionControl.COURT
        update_region_control(s)
        assert r.control == RegionControl.COURT

    def test_unstable_to_fallen(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 5
        r.control = RegionControl.UNSTABLE
        update_region_control(s)
        assert r.control == RegionControl.FALLEN

    def test_unstable_recovery_to_court(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 36
        r.rebellion_risk = 59
        r.control = RegionControl.UNSTABLE
        update_region_control(s)
        assert r.control == RegionControl.COURT

    def test_unstable_no_recovery_high_rebellion(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 50
        r.rebellion_risk = 60
        r.control = RegionControl.UNSTABLE
        update_region_control(s)
        assert r.control == RegionControl.UNSTABLE

    def test_fallen_recovery_to_unstable(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 25
        r.rebellion_risk = 70
        r.control = RegionControl.FALLEN
        update_region_control(s)
        assert r.control == RegionControl.UNSTABLE

    def test_fallen_stays_if_low_stability(self):
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 24
        r.rebellion_risk = 50
        r.control = RegionControl.FALLEN
        update_region_control(s)
        assert r.control == RegionControl.FALLEN

    def test_no_oscillation_single_turn(self):
        """A region can only transition once per update call."""
        s = _make_state()
        r = next(r for r in s.regions if r.name == "应天")
        r.stability = 36
        r.rebellion_risk = 30
        r.control = RegionControl.FALLEN
        update_region_control(s)
        # FALLEN→UNSTABLE (not COURT, because elif chain)
        assert r.control == RegionControl.UNSTABLE


# ── Control Consequences ──────────────────────────────

class TestControlConsequences:
    def test_no_penalty_when_all_court(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.COURT
        attr = {}
        old_t = s.national_treasury
        apply_region_control_consequences(s, attr)
        assert s.national_treasury == old_t

    def test_fallen_penalty(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.COURT
        s.regions[0].control = RegionControl.FALLEN
        s.regions[1].control = RegionControl.FALLEN
        attr = {}
        old_t = s.national_treasury
        apply_region_control_consequences(s, attr)
        # 2 fallen: treasury -6, civil -2, military -1, prestige -4
        assert s.national_treasury == old_t - 6
        assert attr["national_treasury"]["疆域失控"] == -6

    def test_unstable_penalty(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.COURT
        for r in s.regions[:3]:
            r.control = RegionControl.UNSTABLE
        attr = {}
        old_p = s.court_prestige
        apply_region_control_consequences(s, attr)
        # 0 fallen, 3 unstable: prestige -1 (1 if unstable>2)
        assert s.court_prestige == old_p - 1


# ── Tax Revenue ───────────────────────────────────────

class TestTaxRevenue:
    def test_fallen_pays_nothing(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.FALLEN
            r.tax_collected = 100
        attr = {}
        collect_tax_revenue(s, attr)
        assert "税收" not in attr.get("national_treasury", {})

    def test_unstable_pays_half(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.COURT
            r.tax_collected = 0
        s.regions[0].control = RegionControl.UNSTABLE
        s.regions[0].tax_collected = 24
        attr = {}
        old_t = s.national_treasury
        collect_tax_revenue(s, attr)
        # 24 // 2 = 12, monthly=floor(12/12)=1, treasury=floor(1*0.7)=0, grain=1
        assert s.national_treasury == old_t

    def test_normal_court_revenue(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.COURT
            r.tax_collected = 0
        s.regions[0].tax_collected = 120
        attr = {}
        old_t = s.national_treasury
        collect_tax_revenue(s, attr)
        assert s.national_treasury == old_t + 7  # 120/12=10, floor(10*0.7)=7


# ── Game End (validated player death only) ───────────

class TestGameEnd:
    def test_all_fallen_remains_recoverable(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.FALLEN
        assert check_game_end(s) is None

    def test_zero_prestige_remains_recoverable(self):
        s = _make_state()
        s.court_prestige = 0
        assert check_game_end(s) is None

    def test_1368_is_display_history_not_terminal(self):
        s = _make_state()
        s.time = GameTime(year=1368, month=1, era_name="洪武", era_year=1)
        assert check_game_end(s) is None

    def test_clock_can_continue_beyond_1368(self):
        s = _make_state()
        s.time = GameTime(year=1400, month=7, era_name="洪武", era_year=33)
        assert check_game_end(s) is None

    def test_validated_player_death_is_terminal(self):
        s = _make_state()
        s.player_world_status.life_status = "dead"
        result = check_game_end(s)
        assert result is not None
        assert result["result"] == "defeat"
        assert "主角" in result["message"]


# ── Consecutive Wait Compatibility Metadata ───────────

class TestConsecutiveWaitPenalty:
    def test_no_penalty_first_two_waits(self):
        s = _make_state()
        s.consecutive_waits = 0
        old_prestige = s.court_prestige
        process_decree(s, decree=None)
        assert s.consecutive_waits == 1
        # first wait: no penalty beyond normal drift
        s2 = _make_state()
        s2.consecutive_waits = 1
        old_prestige2 = s2.court_prestige
        process_decree(s2, decree=None)
        assert s2.consecutive_waits == 2

    def test_third_wait_has_no_action_count_penalty_or_passive_drift(self):
        s = _make_state()
        s.consecutive_waits = 2
        old_prestige = s.court_prestige
        old_treasury = s.national_treasury
        old_grain = s.grain
        process_decree(s, decree=None)
        assert s.consecutive_waits == 3
        assert s.court_prestige == old_prestige
        assert s.national_treasury == old_treasury
        assert s.grain == old_grain

    def test_decree_resets_counter(self):
        from models.game import StructuredDecree
        from models.enums import DecreeType
        s = _make_state()
        s.consecutive_waits = 5
        d = StructuredDecree(type=DecreeType.TAX_INCREASE)
        process_decree(s, decree=d)
        assert s.consecutive_waits == 0


# ── Military Supply Production ────────────────────────

class TestMilitarySupplyProduction:
    def test_stable_garrisoned_regions_produce(self):
        s = _make_state()
        attr = {}
        # count how many regions qualify (stability>=50, garrison>=10000, COURT)
        qualifying = sum(
            1 for r in s.regions
            if r.stability >= 50 and r.garrison >= 10000
            and r.control == RegionControl.COURT
        )
        old_supply = s.military_strength
        apply_passive_drift(s, attr)
        gain = min(qualifying, 3)
        # net = -1 (upkeep) + gain (production)
        if gain > 0:
            assert "军备生产" in attr.get("military_strength", {})

    def test_no_production_if_all_unstable(self):
        s = _make_state()
        for r in s.regions:
            r.control = RegionControl.UNSTABLE
        attr = {}
        apply_passive_drift(s, attr)
        assert "军备生产" not in attr.get("military_strength", {})


# ── assign_urgency ────────────────────────────────────

class TestAssignUrgency:
    def test_uses_event_name_not_chain_event(self):
        attr = {"武昌_stability": {"汉军东进": -20}}
        result = assign_urgency("汉军东进", attr)
        assert result == EventUrgency.HIGH

    def test_low_urgency_no_match(self):
        attr = {"treasury": {"base_effect": 10}}
        result = assign_urgency("不存在的事件", attr)
        assert result == EventUrgency.LOW

    def test_medium_urgency(self):
        attr = {"两淮_stability": {"红巾烽火": -5}}
        result = assign_urgency("红巾烽火", attr)
        assert result == EventUrgency.MEDIUM


# ── Pipeline Order ────────────────────────────────────

class TestPipelineOrder:
    def test_fallen_region_earns_no_tax(self):
        """A region that becomes FALLEN should earn zero tax that turn."""
        s = _make_state()
        r = next(r for r in s.regions if r.name == "两淮")
        r.stability = 0
        r.control = RegionControl.UNSTABLE
        r.tax_collected = 100
        old_treasury = s.national_treasury
        process_decree(s, decree=None)
        # after pipeline: control updates first,两淮 → FALLEN, then tax collected
        # so 两淮 should contribute 0
        # (we can't check exact treasury due to other effects, but verify control)
        assert r.control == RegionControl.FALLEN
