from models.game import (
    GameState, GameTime, Faction, Region, create_initial_state,
    RegionChange, GameEvent,
)
from models.enums import TaxContribution, MinisterStatus
from engine.core import inject_script_events, _script_to_event
from engine.scripts import get_scripts_for_time, SCRIPT_REGISTRY, ScriptEvent, ScriptChoice, _register


def _minimal_state(year=1627, month=8) -> GameState:
    return GameState(
        time=GameTime(year=year, month=month, era_name="天启", era_year=7),
        factions=[Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10)],
        regions=[Region(name="test", stability=50, garrison=10000,
                        tax_contribution=TaxContribution.MEDIUM)],
    )


# ── 10.4 All 13 new script events register correctly ──

MONTHLY_EVENT_IDS = [
    "chongzhen-accession-1627-08",
    "court-ceremonies-1627-09",
    "qian-jiazheng-impeachment-1627-10",
    "wei-zhongxian-falls-1627-11",
    "eunuch-party-purge-1627-12",
    "donglin-restoration-1628-01",
    "rehabilitation-begins-1628-02",
    "tianqi-burial-1628-03",
    "yuan-chonghuan-appointed-1628-04",
    "farmer-uprising-erupts-1628-05",
    "famine-escalates-1628-06",
    "ningyuan-mutiny-1628-07",
    "year-end-assessment-1628-08",
]

CONDITIONAL_MONTHLY_EVENT_IDS = {
    "qian-jiazheng-impeachment-1627-10",
    "wei-zhongxian-falls-1627-11",
}

BRANCH_EVENT_IDS = [
    "post-wei-vacuum-1627-10",
    "post-wei-remnant-settlement-1627-11",
    "liaodong-command-vacancy-1629-12",
]


class TestNewMonthlyEvents:
    def test_all_13_events_registered(self):
        for sid in MONTHLY_EVENT_IDS:
            assert sid in SCRIPT_REGISTRY, f"{sid} not in SCRIPT_REGISTRY"

    def test_events_trigger_in_correct_sequence(self):
        expected_times = [
            (1627, 8), (1627, 9), (1627, 10), (1627, 11), (1627, 12),
            (1628, 1), (1628, 2), (1628, 3), (1628, 4),
            (1628, 5), (1628, 6), (1628, 7), (1628, 8),
        ]
        for sid, (y, m) in zip(MONTHLY_EVENT_IDS, expected_times):
            evt = SCRIPT_REGISTRY[sid]
            assert evt.trigger_year == y, f"{sid}: expected year {y}, got {evt.trigger_year}"
            assert evt.trigger_month == m, f"{sid}: expected month {m}, got {evt.trigger_month}"

    def test_all_events_have_canonical_script_ids(self):
        for sid in MONTHLY_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            assert evt.script_id == sid

    def test_all_events_have_choices(self):
        for sid in MONTHLY_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            assert len(evt.choices) >= 1, f"{sid} has no choices"

    def test_blocking_events_correct(self):
        blocking = {"chongzhen-accession-1627-08", "wei-zhongxian-falls-1627-11",
                     "farmer-uprising-erupts-1628-05", "ningyuan-mutiny-1628-07",
                     "year-end-assessment-1628-08"}
        for sid in MONTHLY_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            if sid in blocking:
                assert evt.is_blocking, f"{sid} should be blocking"
            else:
                assert not evt.is_blocking, f"{sid} should not be blocking"

    def test_no_conditions_on_monthly_events(self):
        for sid in MONTHLY_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            if sid in CONDITIONAL_MONTHLY_EVENT_IDS:
                assert evt.condition is not None, f"{sid} should have branching condition"
            else:
                assert evt.condition is None, f"{sid} should have no condition"

    def test_branch_events_registered(self):
        for sid in BRANCH_EVENT_IDS:
            assert sid in SCRIPT_REGISTRY, f"{sid} not in SCRIPT_REGISTRY"
            assert SCRIPT_REGISTRY[sid].condition is not None, f"{sid} should be conditional"


# ── 10.5 Deleted events no longer in registry ──

DELETED_EVENT_IDS = [
    "tianqi-7-opening",
    "eunuch-backlash",
    "donglin-impeachment",
    "shaanxi-famine-memorial",
    "rebel-wangjiaying",
    "ningyuan-mutiny",  # old event, replaced by ningyuan-mutiny-1628-07
]


class TestDeletedEvents:
    def test_deleted_events_not_in_registry(self):
        for sid in DELETED_EVENT_IDS:
            assert sid not in SCRIPT_REGISTRY, f"{sid} should have been deleted"


# ── 10.6 1629+ events remain unchanged ──

class TestExistingEventsUnchanged:
    def test_jisi_invasion_unchanged(self):
        assert "jisi-invasion" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["jisi-invasion"]
        assert evt.trigger_year == 1629
        assert evt.trigger_month == 10
        assert evt.is_blocking is True
        assert evt.condition is None

    def test_yuan_chonghuan_arrest_unchanged(self):
        assert "yuan-chonghuan-arrest" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["yuan-chonghuan-arrest"]
        assert evt.trigger_year == 1629
        assert evt.trigger_month == 12
        assert evt.condition is not None

    def test_li_zicheng_joins_unchanged(self):
        assert "li-zicheng-joins" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["li-zicheng-joins"]
        assert evt.trigger_year == 1630
        assert evt.trigger_month == 3

    def test_sun_chengzong_recovery_unchanged(self):
        assert "sun-chengzong-recovery" in SCRIPT_REGISTRY
        evt = SCRIPT_REGISTRY["sun-chengzong-recovery"]
        assert evt.trigger_year == 1630
        assert evt.trigger_month == 5


# ── 10.8 Game start time ──

class TestGameStartTime:
    def test_initial_state_month_is_8(self):
        state = create_initial_state()
        assert state.time.month == 8

    def test_initial_state_year_is_1627(self):
        state = create_initial_state()
        assert state.time.year == 1627

    def test_initial_state_has_opening_event(self):
        state = create_initial_state()
        scripted = [e for e in state.active_events if e.is_scripted]
        assert len(scripted) >= 1
        assert any(e.script_id == "chongzhen-accession-1627-08" for e in scripted)

    def test_opening_event_is_blocking(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events
                   if e.script_id == "chongzhen-accession-1627-08")
        assert evt.is_blocking is True

    def test_opening_event_has_rich_description(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events
                   if e.script_id == "chongzhen-accession-1627-08")
        assert evt.rich_description
        assert len(evt.rich_description) > 50


# ── 10.9 dalinghe-prelude at 1631/8 ──

class TestDalinghePrelude:
    def test_trigger_year_is_1631(self):
        evt = SCRIPT_REGISTRY["dalinghe-prelude"]
        assert evt.trigger_year == 1631

    def test_trigger_month_is_8(self):
        evt = SCRIPT_REGISTRY["dalinghe-prelude"]
        assert evt.trigger_month == 8

    def test_old_trigger_time_has_no_match(self):
        scripts = get_scripts_for_time(1630, 9)
        assert not any(s.script_id == "dalinghe-prelude" for s in scripts)

    def test_new_trigger_time_has_match(self):
        scripts = get_scripts_for_time(1631, 8)
        assert any(s.script_id == "dalinghe-prelude" for s in scripts)


# ── 10.7 Backward compat: old RegionChange without new fields ──

class TestRegionChangeBackwardCompat:
    def test_old_fields_only_deserializes(self):
        rc = RegionChange(
            name="辽东",
            stability_before=50, stability_after=45,
            control_before="朝廷", control_after="朝廷",
            threat_before="后金", threat_after="后金",
        )
        assert rc.garrison_before is None
        assert rc.garrison_after is None
        assert rc.civil_morale_before is None
        assert rc.tax_rate_before is None
        assert rc.tax_contribution_before is None

    def test_new_fields_populated(self):
        rc = RegionChange(
            name="陕西",
            stability_before=30, stability_after=25,
            control_before="朝廷", control_after="失控",
            threat_before="none", threat_after="民变",
            garrison_before=5000, garrison_after=3000,
            civil_morale_before=40, civil_morale_after=30,
        )
        assert rc.garrison_before == 5000
        assert rc.garrison_after == 3000
        assert rc.civil_morale_before == 40
        assert rc.civil_morale_after == 30
        assert rc.rebellion_risk_before is None


# ── Script injection and dedup (updated for new events) ──

class TestScriptDedup:
    def test_no_duplicate_in_active_events(self):
        state = _minimal_state()
        injected1 = inject_script_events(state)
        assert len(injected1) == 1
        injected2 = inject_script_events(state)
        assert len(injected2) == 0
        scripted = [e for e in state.active_events
                    if e.script_id == "chongzhen-accession-1627-08"]
        assert len(scripted) == 1

    def test_no_inject_if_in_resolved(self):
        state = _minimal_state()
        state.resolved_script_ids.add("chongzhen-accession-1627-08")
        injected = inject_script_events(state)
        assert len(injected) == 0
        assert not any(e.script_id == "chongzhen-accession-1627-08"
                       for e in state.active_events)

    def test_non_matching_time_not_injected(self):
        state = _minimal_state(year=1635, month=6)
        injected = inject_script_events(state)
        assert len(injected) == 0


class TestKeyFigureLifeDeathBranching:
    def _state_for_month(self, year: int, month: int) -> GameState:
        state = create_initial_state()
        state.time.year = year
        state.time.month = month
        state.active_events = []
        state.resolved_script_ids = set()
        return state

    def _set_minister_status(self, state: GameState, name: str, status: MinisterStatus) -> None:
        minister = next(m for m in state.ministers if m.name == name)
        minister.status = status

    def test_wei_removed_triggers_october_fallback(self):
        state = self._state_for_month(1627, 10)
        self._set_minister_status(state, "魏忠贤", MinisterStatus.REMOVED)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "post-wei-vacuum-1627-10" in ids
        assert "qian-jiazheng-impeachment-1627-10" not in ids

    def test_wei_removed_triggers_november_fallback(self):
        state = self._state_for_month(1627, 11)
        self._set_minister_status(state, "魏忠贤", MinisterStatus.REMOVED)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "post-wei-remnant-settlement-1627-11" in ids
        assert "wei-zhongxian-falls-1627-11" not in ids

    def test_yuan_removed_triggers_1629_12_fallback(self):
        state = self._state_for_month(1629, 12)
        state.resolved_script_ids.add("jisi-invasion")
        self._set_minister_status(state, "袁崇焕", MinisterStatus.REMOVED)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "liaodong-command-vacancy-1629-12" in ids
        assert "yuan-chonghuan-arrest" not in ids


class TestSourceScriptIdCleanup:
    def test_remove_event_on_resolve(self):
        state = _minimal_state()
        inject_script_events(state)
        sid = "chongzhen-accession-1627-08"
        assert any(e.script_id == sid for e in state.active_events)
        before = len(state.active_events)
        state.active_events = [e for e in state.active_events if e.script_id != sid]
        if len(state.active_events) != before:
            state.resolved_script_ids.add(sid)
        assert not any(e.script_id == sid for e in state.active_events)
        assert sid in state.resolved_script_ids

    def test_resolved_prevents_re_injection(self):
        state = _minimal_state()
        inject_script_events(state)
        sid = "chongzhen-accession-1627-08"
        state.active_events = [e for e in state.active_events if e.script_id != sid]
        state.resolved_script_ids.add(sid)
        injected = inject_script_events(state)
        assert len(injected) == 0


class TestScriptRegistryIntegrity:
    def test_registry_has_opening(self):
        assert "chongzhen-accession-1627-08" in SCRIPT_REGISTRY

    def test_get_scripts_for_time_1627_8(self):
        scripts = get_scripts_for_time(1627, 8)
        assert len(scripts) >= 1
        assert any(s.script_id == "chongzhen-accession-1627-08" for s in scripts)

    def test_get_scripts_for_time_miss(self):
        scripts = get_scripts_for_time(1635, 6)
        assert len(scripts) == 0

    def test_all_registered_scripts_valid(self):
        for sid, evt in SCRIPT_REGISTRY.items():
            assert 1621 <= evt.trigger_year <= 1644
            assert 1 <= evt.trigger_month <= 12
            assert len(evt.choices) >= 1
            assert evt.historical_hint.strip(), f"{sid} has empty historical_hint"
            assert len(evt.historical_hint) >= 120, f"{sid} historical_hint too short"
            assert "。" in evt.historical_hint, f"{sid} historical_hint should contain complete sentences"
            assert "**" not in evt.historical_hint, f"{sid} historical_hint should not use markdown bold markers"


# ── Historical hint tests ──────────────────────────────

class TestHistoricalHintConversion:
    def test_script_to_event_passes_historical_hint(self):
        evt = SCRIPT_REGISTRY["chongzhen-accession-1627-08"]
        ge = _script_to_event(evt, 1627, 8)
        assert ge.historical_hint == evt.historical_hint

    def test_all_events_hint_survives_conversion(self):
        for sid, evt in SCRIPT_REGISTRY.items():
            ge = _script_to_event(evt, evt.trigger_year, evt.trigger_month)
            assert ge.historical_hint == evt.historical_hint, f"{sid} hint mismatch"


class TestRegisterRejectsEmptyHint:
    def test_empty_string_rejected(self):
        size_before = len(SCRIPT_REGISTRY)
        import pytest
        with pytest.raises(ValueError, match="must have non-empty historical_hint"):
            _register(ScriptEvent(
                script_id="test-empty-hint",
                trigger_year=1627, trigger_month=8,
                title="test", rich_description="test",
                choices=[ScriptChoice(label="a", description="b")],
                historical_hint="",
            ))
        assert len(SCRIPT_REGISTRY) == size_before

    def test_whitespace_only_rejected(self):
        size_before = len(SCRIPT_REGISTRY)
        import pytest
        with pytest.raises(ValueError, match="must have non-empty historical_hint"):
            _register(ScriptEvent(
                script_id="test-whitespace-hint",
                trigger_year=1627, trigger_month=8,
                title="test", rich_description="test",
                choices=[ScriptChoice(label="a", description="b")],
                historical_hint="   \n\t  ",
            ))
        assert len(SCRIPT_REGISTRY) == size_before

    def test_none_rejected(self):
        size_before = len(SCRIPT_REGISTRY)
        import pytest
        with pytest.raises(ValueError, match="must have non-empty historical_hint"):
            _register(ScriptEvent(
                script_id="test-none-hint",
                trigger_year=1627, trigger_month=8,
                title="test", rich_description="test",
                choices=[ScriptChoice(label="a", description="b")],
                historical_hint=None,  # type: ignore[arg-type]
            ))
        assert len(SCRIPT_REGISTRY) == size_before


class TestRegistryCompleteness:
    def test_registry_count_is_21(self):
        assert len(SCRIPT_REGISTRY) == 21


class TestGameEventBackwardCompat:
    def test_old_save_without_historical_hint(self):
        ge = GameEvent.model_validate({
            "name": "x",
            "triggered_year": 1627,
            "triggered_month": 8,
        })
        assert ge.historical_hint == ""
