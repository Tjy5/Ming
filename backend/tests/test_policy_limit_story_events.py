import asyncio

import pytest
from fastapi import HTTPException

from ai.provider import MockProvider, ResilientProvider
from api import routes
from api import state as api_state
from db.saves import _migrate_save
from engine.core import check_preconditions, inject_script_events, process_decree
from engine.scripts import get_scripts_for_time
from models.enums import DecreeType, MinisterStatus, PersonnelAction, TaxContribution
from models.game import (
    Faction,
    GameState,
    GameTime,
    Region,
    StructuredDecree,
    TriggerDecision,
    create_initial_state,
)


@pytest.fixture(autouse=True)
def _restore_route_globals():
    old_state = api_state._state
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider


def _mock_provider():
    return ResilientProvider(MockProvider(), timeout=1, retries=1)


def _governance_opening_state():
    """治理开局态：拨到切换点 1356-03 + 注入脚本事件 + 激活已入仕大臣。

    （新档开局 1328-10 为跑团开局：无治理脚本事件、大臣均未入仕。）
    """
    state = create_initial_state()
    state.time = GameTime(year=1356, month=3, era_name="至正", era_year=16)
    inject_script_events(state)
    for m in state.ministers:
        if m.status == MinisterStatus.NOT_YET_ENTERED:
            m.status = MinisterStatus.ACTIVE if m.positions else MinisterStatus.IDLE
    return state


def test_panel_decree_limit_is_category_keyed():
    state = create_initial_state()

    process_decree(state, StructuredDecree(type=DecreeType.TAX_INCREASE))
    assert state.decrees_this_month == {"domestic": True}

    reason_same_category = check_preconditions(
        state,
        StructuredDecree(type=DecreeType.TAX_DECREASE),
    )
    assert reason_same_category == "本月已下达此类政令"

    reason_other_category = check_preconditions(
        state,
        StructuredDecree(type=DecreeType.RECRUIT_TROOPS),
    )
    assert reason_other_category is None


def test_non_panel_decree_is_exempt_from_monthly_limit():
    state = create_initial_state()
    state.decrees_this_month = {"other": True}

    decree = StructuredDecree(
        type=DecreeType.PERSONNEL,
        target="杨宪",
        sub_action=PersonnelAction.DISMISS,
    )
    assert check_preconditions(state, decree, enforce_monthly_limit=False) is None
    process_decree(state, decree, mark_monthly_usage=False)
    assert state.decrees_this_month == {"other": True}


def test_migrate_decrees_this_month_from_type_keys_to_categories():
    data = {
        "time": {"year": 1630, "month": 6},
        "treasury": 100,
        "population": 100,
        "military_supply": 80,
        "civil_morale": 60,
        "military_morale": 70,
        "court_prestige": 75,
        "factions": [],
        "active_events": [],
        "history_log": [],
        "decree_count": 5,
        "event_cooldowns": {},
        "regions": [],
        "decrees_this_month": {
            "tax_increase": True,
            "tax_decrease": True,
            "diplomacy": True,
            "personnel": False,
        },
    }
    _migrate_save(data)
    assert data["decrees_this_month"] == {"domestic": True, "diplomacy": True}


def test_script_free_text_maps_to_choice_and_executes():
    api_state._provider = _mock_provider()
    state = _governance_opening_state()
    api_state._state = state

    active_script = next((e.script_id for e in state.active_events if e.script_id), None)
    assert active_script is not None

    result = asyncio.run(routes.execute_decree(
        routes.DecreeRequest(
            source_script_id=active_script,
            free_text="裁汰冗员，整肃幕府",
        )
    ))

    yang = next(m for m in result["state"]["ministers"] if m["name"] == "杨宪")
    assert yang["status"] == "idle"
    assert active_script in result["state"]["resolved_script_ids"]
    assert result["state"]["decrees_this_month"] == {}


def test_script_free_text_low_confidence_returns_freeform_empty_and_preserves_state():
    api_state._provider = _mock_provider()
    state = _governance_opening_state()
    api_state._state = state
    before = state.model_dump()

    active_script = next((e.script_id for e in state.active_events if e.script_id), None)
    assert active_script is not None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.execute_decree(
            routes.DecreeRequest(
                source_script_id=active_script,
                free_text="!!!",
            )
        ))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "FREEFORM_EMPTY"
    assert api_state._state is not None
    assert api_state._state.model_dump() == before


def test_inject_script_events_respects_persisted_trigger_decision():
    state = GameState(
        time=GameTime(year=1356, month=3, era_name="至正", era_year=16),
        factions=[Faction(name="test", satisfaction=50, influence=50, rebellion_risk=10)],
        regions=[Region(name="test", stability=50, garrison=10000, tax_contribution=TaxContribution.MEDIUM)],
    )
    script_id = "yingtian-founding-1356-03"
    state.trigger_decisions[script_id] = TriggerDecision(
        should_trigger=False,
        reason="manual",
        timestamp="1356-03",
    )

    injected = inject_script_events(state)

    assert injected == []
    assert not any(e.script_id == script_id for e in state.active_events)


def test_script_free_text_uses_provider_classification_path():
    class _TrackingProvider(MockProvider):
        def __init__(self):
            self.classify_called = False

        async def classify_script_choice(self, *a, **kw):
            self.classify_called = True
            return {"choice_index": 0, "confidence": 0.95, "reason": "test"}

    inner = _TrackingProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)
    state = _governance_opening_state()
    api_state._state = state
    active_script = next((e.script_id for e in state.active_events if e.script_id), None)
    assert active_script is not None

    result = asyncio.run(routes.execute_decree(
        routes.DecreeRequest(
            source_script_id=active_script,
            free_text="按此办理",
        )
    ))

    assert inner.classify_called is True
    assert active_script in result["state"]["resolved_script_ids"]


def test_advance_month_uses_provider_trigger_decisions():
    class _TrackingProvider(MockProvider):
        def __init__(self):
            self.trigger_called = False

        async def select_script_trigger_decisions(self, game_state, candidates):
            self.trigger_called = True
            return {
                str(item.get("script_id")): (False, "test block")
                for item in candidates
                if isinstance(item, dict) and item.get("script_id")
            }

    inner = _TrackingProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)
    api_state._state = _governance_opening_state()
    # 推进至 1356/7（龙凤册命事件触发月）
    api_state._state.time.month = 6

    result = asyncio.run(routes.advance_month_endpoint())
    month7_script_ids = [s.script_id for s in get_scripts_for_time(1356, 7)]

    assert inner.trigger_called is True
    assert len(month7_script_ids) >= 1
    for script_id in month7_script_ids:
        assert script_id in result["state"]["trigger_decisions"]
        assert result["state"]["trigger_decisions"][script_id]["should_trigger"] is False
    active_ids = {e["script_id"] for e in result["state"]["active_events"] if e.get("script_id")}
    for script_id in month7_script_ids:
        assert script_id not in active_ids


def test_new_game_is_trpg_opening_without_governance_scripts():
    """新档开局 1328-10 为跑团开局：无治理脚本候选，AI 触发决策不被调用。

    （治理脚本自 1356-03 起，经 advance-month 的 AI 决策路径注入——
    见 test_advance_month_uses_provider_trigger_decisions。）
    """
    class _TrackingProvider(MockProvider):
        def __init__(self):
            self.trigger_called = False

        async def select_script_trigger_decisions(self, game_state, candidates):
            self.trigger_called = True
            return {
                str(item.get("script_id")): (False, "test block")
                for item in candidates
                if isinstance(item, dict) and item.get("script_id")
            }

    inner = _TrackingProvider()
    api_state._provider = ResilientProvider(inner, timeout=1, retries=1)

    result = asyncio.run(routes.new_game())
    opening_script = "yingtian-founding-1356-03"
    active_ids = {e["script_id"] for e in result["active_events"] if e.get("script_id")}

    assert inner.trigger_called is False
    assert result["trigger_decisions"] == {}
    assert opening_script not in active_ids
    assert result["time"]["year"] == 1328
    assert result["phase"] == "life_story"
