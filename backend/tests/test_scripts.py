from models.game import (
    GameState, GameTime, Faction, Region, create_initial_state,
    RegionChange, GameEvent,
)
from models.enums import TaxContribution, MinisterStatus
from engine.core import inject_script_events, _script_to_event
from engine.scripts import get_scripts_for_time, SCRIPT_REGISTRY, ScriptEvent, ScriptChoice, _register


def _minimal_state(year=1356, month=3) -> GameState:
    return GameState(
        time=GameTime(year=year, month=month, era_name="至正", era_year=16),
        factions=[Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10)],
        regions=[Region(name="test", stability=50, garrison=10000,
                        tax_contribution=TaxContribution.MEDIUM)],
    )


# ── 元末治理阶段事件集（1356–1367）──

MONTHLY_EVENT_IDS = [
    "yingtian-founding-1356-03",
    "longfeng-commission-1356-07",
    "zhenjiang-campaign-1356-10",
    "changzhou-frontier-1357-04",
    "zhusheng-three-counsels-1358-11",
    "zhedong-talents-1360-03",
    "chen-han-proclamation-1360-05",
    "longwan-battle-1360-06",
    "wuguo-duke-1361-01",
    "anfeng-siege-1363-03",
    "poyang-battle-1363-07",
    "wu-king-proclamation-1364-01",
    "guabu-incident-1366-12",
    "northern-expedition-1367-10",
]

CONDITIONAL_EVENT_IDS = [
    "yangxian-discipline-1357-02",
    "post-yangxian-vacancy-1357-02",
    "redturban-remnants-1357-06",
    "xuda-eastern-campaign-1358-05",
    "chen-youliang-endgame-1363-09",
    "han-regroup-1363-09",
    "pingjiang-siege-1366-08",
    "pingjiang-fall-1367-09",
    "fang-guozhen-surrender-1367-11",
]

BLOCKING_EVENT_IDS = {
    "yingtian-founding-1356-03",
    "chen-han-proclamation-1360-05",
    "longwan-battle-1360-06",
    "anfeng-siege-1363-03",
    "poyang-battle-1363-07",
    "wu-king-proclamation-1364-01",
    "northern-expedition-1367-10",
}

BRANCH_EVENT_IDS = [
    "post-yangxian-vacancy-1357-02",
    "han-regroup-1363-09",
]

ALL_EVENT_IDS = MONTHLY_EVENT_IDS + CONDITIONAL_EVENT_IDS


class TestEventRegistration:
    def test_all_events_registered(self):
        for sid in ALL_EVENT_IDS:
            assert sid in SCRIPT_REGISTRY, f"{sid} not in SCRIPT_REGISTRY"

    def test_registry_count(self):
        assert len(SCRIPT_REGISTRY) == len(ALL_EVENT_IDS)

    def test_unconditional_events_trigger_times(self):
        expected_times = [
            (1356, 3), (1356, 7), (1356, 10),
            (1357, 4), (1358, 11), (1360, 3), (1360, 5), (1360, 6),
            (1361, 1), (1363, 3), (1363, 7), (1364, 1), (1366, 12), (1367, 10),
        ]
        for sid, (y, m) in zip(MONTHLY_EVENT_IDS, expected_times):
            evt = SCRIPT_REGISTRY[sid]
            assert evt.trigger_year == y, f"{sid}: expected year {y}, got {evt.trigger_year}"
            assert evt.trigger_month == m, f"{sid}: expected month {m}, got {evt.trigger_month}"

    def test_conditional_events_trigger_times(self):
        expected_times = [
            (1357, 2), (1357, 2), (1357, 6), (1358, 5),
            (1363, 9), (1363, 9), (1366, 8), (1367, 9), (1367, 11),
        ]
        for sid, (y, m) in zip(CONDITIONAL_EVENT_IDS, expected_times):
            evt = SCRIPT_REGISTRY[sid]
            assert evt.trigger_year == y, f"{sid}: expected year {y}, got {evt.trigger_year}"
            assert evt.trigger_month == m, f"{sid}: expected month {m}, got {evt.trigger_month}"

    def test_all_events_have_canonical_script_ids(self):
        for sid in ALL_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            assert evt.script_id == sid

    def test_all_events_have_choices(self):
        for sid in ALL_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            assert len(evt.choices) >= 1, f"{sid} has no choices"

    def test_blocking_events_correct(self):
        for sid in ALL_EVENT_IDS:
            evt = SCRIPT_REGISTRY[sid]
            if sid in BLOCKING_EVENT_IDS:
                assert evt.is_blocking, f"{sid} should be blocking"
            else:
                assert not evt.is_blocking, f"{sid} should not be blocking"

    def test_conditions_on_events(self):
        for sid in MONTHLY_EVENT_IDS:
            assert SCRIPT_REGISTRY[sid].condition is None, f"{sid} should have no condition"
        for sid in CONDITIONAL_EVENT_IDS:
            assert SCRIPT_REGISTRY[sid].condition is not None, f"{sid} should have a condition"

    def test_branch_events_registered(self):
        for sid in BRANCH_EVENT_IDS:
            assert sid in SCRIPT_REGISTRY, f"{sid} not in SCRIPT_REGISTRY"
            assert SCRIPT_REGISTRY[sid].condition is not None, f"{sid} should be conditional"


# ── 已删除的崇祯旧事件不再注册 ──

DELETED_EVENT_IDS = [
    "chongzhen-accession-1627-08",
    "court-ceremonies-1627-09",
    "wei-zhongxian-falls-1627-11",
    "eunuch-party-purge-1627-12",
    "jisi-invasion",
    "yuan-chonghuan-arrest",
    "li-zicheng-joins",
    "dalinghe-prelude",
    "tianqi-7-opening",
]


class TestDeletedEvents:
    def test_deleted_events_not_in_registry(self):
        for sid in DELETED_EVENT_IDS:
            assert sid not in SCRIPT_REGISTRY, f"{sid} should have been deleted"


# ── 游戏开局时间与开局事件 ──

class TestGameStartTime:
    def test_initial_state_month_is_3(self):
        state = create_initial_state()
        assert state.time.month == 3

    def test_initial_state_year_is_1356(self):
        state = create_initial_state()
        assert state.time.year == 1356

    def test_initial_state_has_opening_event(self):
        state = create_initial_state()
        scripted = [e for e in state.active_events if e.is_scripted]
        assert len(scripted) >= 1
        assert any(e.script_id == "yingtian-founding-1356-03" for e in scripted)

    def test_opening_event_is_blocking(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events
                   if e.script_id == "yingtian-founding-1356-03")
        assert evt.is_blocking is True

    def test_opening_event_has_rich_description(self):
        state = create_initial_state()
        evt = next(e for e in state.active_events
                   if e.script_id == "yingtian-founding-1356-03")
        assert evt.rich_description
        assert len(evt.rich_description) > 50


# ── 平江之围触发时点 ──

class TestPingjiangSiegeTiming:
    def test_trigger_time_is_1366_8(self):
        evt = SCRIPT_REGISTRY["pingjiang-siege-1366-08"]
        assert evt.trigger_year == 1366
        assert evt.trigger_month == 8

    def test_other_month_has_no_match(self):
        scripts = get_scripts_for_time(1366, 7)
        assert not any(s.script_id == "pingjiang-siege-1366-08" for s in scripts)

    def test_trigger_month_has_match(self):
        scripts = get_scripts_for_time(1366, 8)
        assert any(s.script_id == "pingjiang-siege-1366-08" for s in scripts)


# ── 10.7 Backward compat: old RegionChange without new fields ──

class TestRegionChangeBackwardCompat:
    def test_old_fields_only_deserializes(self):
        rc = RegionChange(
            name="武昌",
            stability_before=50, stability_after=45,
            control_before="朝廷", control_after="朝廷",
            threat_before="汉军", threat_after="汉军",
        )
        assert rc.garrison_before is None
        assert rc.garrison_after is None
        assert rc.civil_morale_before is None
        assert rc.tax_rate_before is None
        assert rc.tax_contribution_before is None

    def test_new_fields_populated(self):
        rc = RegionChange(
            name="两淮",
            stability_before=30, stability_after=25,
            control_before="朝廷", control_after="失控",
            threat_before="none", threat_after="元军",
            garrison_before=5000, garrison_after=3000,
            civil_morale_before=40, civil_morale_after=30,
        )
        assert rc.garrison_before == 5000
        assert rc.garrison_after == 3000
        assert rc.civil_morale_before == 40
        assert rc.civil_morale_after == 30
        assert rc.rebellion_risk_before is None


# ── Script injection and dedup ──

class TestScriptDedup:
    def test_no_duplicate_in_active_events(self):
        state = _minimal_state()
        injected1 = inject_script_events(state)
        assert len(injected1) == 1
        injected2 = inject_script_events(state)
        assert len(injected2) == 0
        scripted = [e for e in state.active_events
                    if e.script_id == "yingtian-founding-1356-03"]
        assert len(scripted) == 1

    def test_no_inject_if_in_resolved(self):
        state = _minimal_state()
        state.resolved_script_ids.add("yingtian-founding-1356-03")
        injected = inject_script_events(state)
        assert len(injected) == 0
        assert not any(e.script_id == "yingtian-founding-1356-03"
                       for e in state.active_events)

    def test_non_matching_time_not_injected(self):
        state = _minimal_state(year=1365, month=6)
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

    def test_yangxian_alive_triggers_discipline_event(self):
        state = self._state_for_month(1357, 2)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "yangxian-discipline-1357-02" in ids
        assert "post-yangxian-vacancy-1357-02" not in ids

    def test_yangxian_removed_triggers_fallback(self):
        state = self._state_for_month(1357, 2)
        self._set_minister_status(state, "杨宪", MinisterStatus.REMOVED)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "post-yangxian-vacancy-1357-02" in ids
        assert "yangxian-discipline-1357-02" not in ids

    def test_chen_alive_triggers_endgame_after_poyang(self):
        state = self._state_for_month(1363, 9)
        state.resolved_script_ids.add("poyang-battle-1363-07")
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "chen-youliang-endgame-1363-09" in ids
        assert "han-regroup-1363-09" not in ids

    def test_chen_removed_triggers_regroup_fallback(self):
        state = self._state_for_month(1363, 9)
        state.resolved_script_ids.add("poyang-battle-1363-07")
        self._set_minister_status(state, "陈友谅", MinisterStatus.REMOVED)
        inject_script_events(state)
        ids = {e.script_id for e in state.active_events}
        assert "han-regroup-1363-09" in ids
        assert "chen-youliang-endgame-1363-09" not in ids


class TestSourceScriptIdCleanup:
    def test_remove_event_on_resolve(self):
        state = _minimal_state()
        inject_script_events(state)
        sid = "yingtian-founding-1356-03"
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
        sid = "yingtian-founding-1356-03"
        state.active_events = [e for e in state.active_events if e.script_id != sid]
        state.resolved_script_ids.add(sid)
        injected = inject_script_events(state)
        assert len(injected) == 0


class TestScriptRegistryIntegrity:
    def test_registry_has_opening(self):
        assert "yingtian-founding-1356-03" in SCRIPT_REGISTRY

    def test_get_scripts_for_time_1356_3(self):
        scripts = get_scripts_for_time(1356, 3)
        assert len(scripts) >= 1
        assert any(s.script_id == "yingtian-founding-1356-03" for s in scripts)

    def test_get_scripts_for_time_miss(self):
        scripts = get_scripts_for_time(1365, 6)
        assert len(scripts) == 0

    def test_all_registered_scripts_valid(self):
        for sid, evt in SCRIPT_REGISTRY.items():
            assert 1328 <= evt.trigger_year <= 1368
            assert 1 <= evt.trigger_month <= 12
            assert len(evt.choices) >= 1
            assert evt.historical_hint.strip(), f"{sid} has empty historical_hint"
            assert len(evt.historical_hint) >= 120, f"{sid} historical_hint too short"
            assert "。" in evt.historical_hint, f"{sid} historical_hint should contain complete sentences"
            assert "**" not in evt.historical_hint, f"{sid} historical_hint should not use markdown bold markers"


# ── Historical hint tests ──────────────────────────────

class TestHistoricalHintConversion:
    def test_script_to_event_passes_historical_hint(self):
        evt = SCRIPT_REGISTRY["yingtian-founding-1356-03"]
        ge = _script_to_event(evt, 1356, 3)
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
                trigger_year=1356, trigger_month=3,
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
                trigger_year=1356, trigger_month=3,
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
                trigger_year=1356, trigger_month=3,
                title="test", rich_description="test",
                choices=[ScriptChoice(label="a", description="b")],
                historical_hint=None,  # type: ignore[arg-type]
            ))
        assert len(SCRIPT_REGISTRY) == size_before


class TestGameEventBackwardCompat:
    def test_old_save_without_historical_hint(self):
        ge = GameEvent.model_validate({
            "name": "x",
            "triggered_year": 1356,
            "triggered_month": 3,
        })
        assert ge.historical_hint == ""
