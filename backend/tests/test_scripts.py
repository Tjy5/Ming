from models.game import (
    GameState, GameTime, Faction, Region, create_initial_state,
)
from models.enums import TaxContribution
from engine.core import inject_script_events
from engine.scripts import get_scripts_for_time, SCRIPT_REGISTRY


def _minimal_state(year=1627, month=10) -> GameState:
    return GameState(
        time=GameTime(year=year, month=month, era_name="天启", era_year=7),
        factions=[Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10)],
        regions=[Region(name="test", stability=50, garrison=10000,
                        tax_contribution=TaxContribution.MEDIUM)],
    )


class TestInitialScriptInjection:
    def test_create_initial_state_has_opening_event(self):
        state = create_initial_state()
        scripted = [e for e in state.active_events if e.is_scripted]
        assert len(scripted) >= 1
        assert any(e.script_id == "tianqi-7-opening" for e in scripted)

    def test_opening_event_has_3_choices(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events if e.script_id == "tianqi-7-opening")
        assert len(evt.choices) == 3

    def test_opening_event_has_rich_description(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events if e.script_id == "tianqi-7-opening")
        assert evt.rich_description
        assert len(evt.rich_description) > 50

    def test_opening_event_at_least_one_no_precondition_choice(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events if e.script_id == "tianqi-7-opening")
        has_safe = any(len(c.decrees) == 0 for c in evt.choices)
        assert has_safe

    def test_opening_event_keeps_blocking_flag(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events if e.script_id == "tianqi-7-opening")
        assert evt.is_blocking is True

    def test_opening_triggers_at_1627_10(self):
        state = create_initial_state()
        assert state.time.year == 1627
        assert state.time.month == 10
        evt = next(e for e in state.active_events if e.script_id == "tianqi-7-opening")
        assert evt.triggered_year == 1627
        assert evt.triggered_month == 10


class TestScriptDedup:
    def test_no_duplicate_in_active_events(self):
        state = _minimal_state()
        injected1 = inject_script_events(state)
        assert len(injected1) == 1
        injected2 = inject_script_events(state)
        assert len(injected2) == 0
        scripted = [e for e in state.active_events if e.script_id == "tianqi-7-opening"]
        assert len(scripted) == 1

    def test_no_inject_if_in_resolved(self):
        state = _minimal_state()
        state.resolved_script_ids.add("tianqi-7-opening")
        injected = inject_script_events(state)
        assert len(injected) == 0
        assert not any(e.script_id == "tianqi-7-opening" for e in state.active_events)

    def test_non_matching_time_not_injected(self):
        state = _minimal_state(year=1630, month=6)
        injected = inject_script_events(state)
        assert len(injected) == 0


class TestSourceScriptIdCleanup:
    def test_remove_event_on_resolve(self):
        state = _minimal_state()
        inject_script_events(state)
        assert any(e.script_id == "tianqi-7-opening" for e in state.active_events)

        sid = "tianqi-7-opening"
        before = len(state.active_events)
        state.active_events = [
            e for e in state.active_events if e.script_id != sid
        ]
        if len(state.active_events) != before:
            state.resolved_script_ids.add(sid)

        assert not any(e.script_id == sid for e in state.active_events)
        assert sid in state.resolved_script_ids

    def test_no_op_if_script_id_not_found(self):
        state = _minimal_state()
        inject_script_events(state)
        before = len(state.active_events)

        sid = "nonexistent-script"
        state.active_events = [
            e for e in state.active_events if e.script_id != sid
        ]
        if len(state.active_events) != before:
            state.resolved_script_ids.add(sid)

        assert len(state.active_events) == before
        assert sid not in state.resolved_script_ids

    def test_resolved_prevents_re_injection(self):
        state = _minimal_state()
        inject_script_events(state)
        sid = "tianqi-7-opening"
        state.active_events = [e for e in state.active_events if e.script_id != sid]
        state.resolved_script_ids.add(sid)
        injected = inject_script_events(state)
        assert len(injected) == 0


class TestScriptRegistryIntegrity:
    def test_registry_has_opening(self):
        assert "tianqi-7-opening" in SCRIPT_REGISTRY

    def test_get_scripts_for_time_1627_10(self):
        scripts = get_scripts_for_time(1627, 10)
        assert len(scripts) >= 1
        assert any(s.script_id == "tianqi-7-opening" for s in scripts)

    def test_get_scripts_for_time_miss(self):
        scripts = get_scripts_for_time(1635, 6)
        assert len(scripts) == 0

    def test_all_registered_scripts_valid(self):
        for sid, evt in SCRIPT_REGISTRY.items():
            assert 1621 <= evt.trigger_year <= 1644
            assert 1 <= evt.trigger_month <= 12
            assert len(evt.choices) >= 1


class TestConditionalScripts:
    def test_eunuch_backlash_conditional(self):
        assert "eunuch-backlash" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["eunuch-backlash"]
        assert evt.condition is not None
        assert evt.trigger_year == 1627
        assert evt.trigger_month == 12

    def test_donglin_impeachment_conditional(self):
        assert "donglin-impeachment" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["donglin-impeachment"]
        assert evt.condition is not None
        assert evt.trigger_year == 1628
        assert evt.trigger_month == 1

    def test_shaanxi_famine_unconditional(self):
        assert "shaanxi-famine-memorial" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["shaanxi-famine-memorial"]
        assert evt.condition is None
        assert evt.is_blocking

    def test_condition_false_skips_injection(self):
        state = _minimal_state(year=1627, month=12)
        state.factions = [Faction(name="阉党残余", satisfaction=50, influence=25, rebellion_risk=20)]
        injected = inject_script_events(state)
        assert "阉党残余反扑" not in injected

    def test_condition_true_injects(self):
        state = _minimal_state(year=1627, month=12)
        state.factions = [Faction(name="阉党残余", satisfaction=50, influence=25, rebellion_risk=50)]
        injected = inject_script_events(state)
        assert "阉党残余反扑" in injected
        evt = next(e for e in state.active_events if e.script_id == "eunuch-backlash")
        assert evt.is_blocking is False

    def test_condition_false_no_resolved(self):
        state = _minimal_state(year=1627, month=12)
        state.factions = [Faction(name="阉党残余", satisfaction=50, influence=25, rebellion_risk=20)]
        inject_script_events(state)
        assert "eunuch-backlash" not in state.resolved_script_ids
