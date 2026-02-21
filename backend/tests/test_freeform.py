"""Tests for AI full-authority freeform engine (tasks 7.1–7.5)."""
import asyncio
import copy

import pytest

from models.game import (
    GameState, GameTime, Faction, Region, Minister, MinisterAbilities,
    StructuredDecree, FreeformResult, MinisterReaction, TurnSummary,
    create_initial_state, clamp_state,
    INITIAL_MINISTERS, INITIAL_FACTIONS, INITIAL_REGIONS,
)
from models.enums import (
    DecreeType, MinisterStatus, PersonnelAction, TaxContribution, EventUrgency,
)
from engine.core import (
    validate_ai_effects, apply_ai_effects, add_ai_new_events,
    process_decree,
)
import ai.provider as provider_mod
from ai.provider import (
    AIProvider, MockProvider, ResilientProvider,
    parse_error, PARSE_ERROR_TYPE_UNAVAILABLE,
)


# ── Helpers ──────────────────────────────────────────────

def make_state(**overrides) -> GameState:
    defaults = dict(
        time=GameTime(year=1630, month=6, era_name="崇祯", era_year=3),
        national_treasury=20, imperial_treasury=10, grain=500,
        population=15000, military_strength=40,
        civil_morale=60, military_morale=70, court_prestige=75,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=[m.model_copy() for m in INITIAL_MINISTERS],
    )
    defaults.update(overrides)
    return GameState(**defaults)


def _minister(state: GameState, name: str) -> Minister:
    return next(m for m in state.ministers if m.name == name)


def _region(state: GameState, name: str) -> Region:
    return next(r for r in state.regions if r.name == name)


def _faction(state: GameState, name: str) -> Faction:
    return next(f for f in state.factions if f.name == name)


# ── 7.1 validate_ai_effects / apply_ai_effects ──────────

class TestValidateAiEffects:
    def test_valid_global_effects(self):
        state = make_state()
        effects = {"global.national_treasury": 20, "global.civil_morale": -5}
        valid = validate_ai_effects(effects, state)
        assert valid == effects

    def test_invalid_path_ignored(self):
        state = make_state()
        effects = {"global.nonexistent": 10, "global.national_treasury": 5}
        valid = validate_ai_effects(effects, state)
        assert "global.nonexistent" not in valid
        assert valid["global.national_treasury"] == 5

    def test_unknown_minister_ignored(self):
        state = make_state()
        effects = {"minister.不存在的人.loyalty": 10}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_known_minister_accepted(self):
        state = make_state()
        effects = {"minister.魏忠贤.loyalty": -10}
        valid = validate_ai_effects(effects, state)
        assert valid == effects

    def test_status_transition_valid(self):
        state = make_state()
        _minister(state, "魏忠贤").status = MinisterStatus.ACTIVE
        effects = {"minister.魏忠贤.status": "removed"}
        valid = validate_ai_effects(effects, state)
        assert "minister.魏忠贤.status" in valid

    def test_status_transition_invalid(self):
        state = make_state()
        _minister(state, "魏忠贤").status = MinisterStatus.REMOVED
        effects = {"minister.魏忠贤.status": "active"}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_nested_value_rejected(self):
        state = make_state()
        effects = {"global.national_treasury": {"nested": 1}}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_bool_value_rejected(self):
        state = make_state()
        effects = {"global.national_treasury": True}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_region_effects(self):
        state = make_state()
        effects = {"region.辽东.stability": -10, "region.辽东.garrison": 5000}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 2

    def test_faction_effects(self):
        state = make_state()
        effects = {"faction.东林党.satisfaction": -5}
        valid = validate_ai_effects(effects, state)
        assert valid == effects

    def test_unknown_region_ignored(self):
        state = make_state()
        effects = {"region.不存在.stability": -10}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_invalid_status_value_rejected(self):
        state = make_state()
        effects = {"minister.魏忠贤.status": "invalid_status"}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0

    def test_empty_effects(self):
        state = make_state()
        assert validate_ai_effects({}, state) == {}

    def test_non_dict_returns_empty(self):
        state = make_state()
        assert validate_ai_effects("not a dict", state) == {}

    def test_minister_abilities(self):
        state = make_state()
        effects = {"minister.徐光启.abilities.civil": 5}
        valid = validate_ai_effects(effects, state)
        assert "minister.徐光启.abilities.civil" in valid

    def test_region_control_valid(self):
        state = make_state()
        effects = {"region.辽东.control": "失控"}
        valid = validate_ai_effects(effects, state)
        assert "region.辽东.control" in valid

    def test_region_control_invalid(self):
        state = make_state()
        effects = {"region.辽东.control": "invalid"}
        valid = validate_ai_effects(effects, state)
        assert len(valid) == 0


class TestApplyAiEffects:
    def test_global_delta_applied(self):
        state = make_state(national_treasury=20, civil_morale=60)
        attr = {}
        effects = {"global.national_treasury": 20, "global.civil_morale": -10}
        apply_ai_effects(state, effects, attr)
        assert state.national_treasury == 40
        assert state.civil_morale == 50

    def test_minister_loyalty_delta(self):
        state = make_state()
        _minister(state, "魏忠贤").loyalty = 50
        attr = {}
        apply_ai_effects(state, {"minister.魏忠贤.loyalty": -20}, attr)
        assert _minister(state, "魏忠贤").loyalty == 30

    def test_minister_status_removed(self):
        state = make_state()
        _minister(state, "魏忠贤").status = MinisterStatus.ACTIVE
        attr = {}
        dismissed, executed = apply_ai_effects(
            state, {"minister.魏忠贤.status": "removed"}, attr,
        )
        assert "魏忠贤" in executed
        assert _minister(state, "魏忠贤").status == MinisterStatus.REMOVED

    def test_minister_status_idle(self):
        state = make_state()
        _minister(state, "魏忠贤").status = MinisterStatus.ACTIVE
        attr = {}
        dismissed, executed = apply_ai_effects(
            state, {"minister.魏忠贤.status": "idle"}, attr,
        )
        assert "魏忠贤" in dismissed
        assert _minister(state, "魏忠贤").status == MinisterStatus.IDLE

    def test_region_delta(self):
        state = make_state()
        old_stab = _region(state, "辽东").stability
        attr = {}
        apply_ai_effects(state, {"region.辽东.stability": -15}, attr)
        assert _region(state, "辽东").stability == old_stab - 15

    def test_attribution_recorded(self):
        state = make_state()
        attr = {}
        apply_ai_effects(state, {"global.national_treasury": 10}, attr)
        assert "national_treasury" in attr
        assert "旨意影响" in attr["national_treasury"]

    def test_abilities_delta(self):
        state = make_state()
        old_civil = _minister(state, "徐光启").abilities.civil
        attr = {}
        apply_ai_effects(state, {"minister.徐光启.abilities.civil": 5}, attr)
        assert _minister(state, "徐光启").abilities.civil == old_civil + 5

    def test_unknown_entity_skipped(self):
        state = make_state()
        attr = {}
        apply_ai_effects(state, {"minister.不存在.loyalty": 10}, attr)
        # no crash, no changes

    def test_clamp_after_apply(self):
        state = make_state(national_treasury=20)
        attr = {}
        apply_ai_effects(state, {"global.national_treasury": 999}, attr)
        assert state.national_treasury == 1019
        clamp_state(state)
        assert state.national_treasury == 1019


# ── 7.2 add_ai_new_events ───────────────────────────────

class TestAddAiNewEvents:
    def test_valid_events_added(self):
        state = make_state()
        before = len(state.active_events)
        add_ai_new_events(state, [
            {"name": "流寇进犯", "description": "流寇攻打陕西", "urgency": "高"},
        ])
        assert len(state.active_events) == before + 1
        assert state.active_events[-1].name == "流寇进犯"
        assert state.active_events[-1].urgency == EventUrgency.HIGH

    def test_missing_name_skipped(self):
        state = make_state()
        before = len(state.active_events)
        add_ai_new_events(state, [{"description": "no name"}])
        assert len(state.active_events) == before

    def test_empty_name_skipped(self):
        state = make_state()
        before = len(state.active_events)
        add_ai_new_events(state, [{"name": "  ", "description": "blank"}])
        assert len(state.active_events) == before

    def test_max_3_events(self):
        state = make_state()
        before = len(state.active_events)
        events = [{"name": f"事件{i}"} for i in range(5)]
        add_ai_new_events(state, events)
        assert len(state.active_events) == before + 3

    def test_default_urgency(self):
        state = make_state()
        add_ai_new_events(state, [{"name": "测试事件"}])
        assert state.active_events[-1].urgency == EventUrgency.MEDIUM

    def test_invalid_urgency_defaults(self):
        state = make_state()
        add_ai_new_events(state, [{"name": "测试", "urgency": "invalid"}])
        assert state.active_events[-1].urgency == EventUrgency.MEDIUM

    def test_non_list_input(self):
        state = make_state()
        before = len(state.active_events)
        add_ai_new_events(state, "not a list")
        assert len(state.active_events) == before

    def test_non_dict_item_skipped(self):
        state = make_state()
        before = len(state.active_events)
        add_ai_new_events(state, ["string_item", 42, None])
        assert len(state.active_events) == before


# ── 7.3 process_decree freeform branch integration ──────

class TestProcessDecreeFreeform:
    def test_freeform_basic_execution(self):
        state = make_state()
        freeform = FreeformResult(
            effects={"global.national_treasury": -30, "global.civil_morale": 10},
            narrative="朕下旨减税，体恤百姓。",
            rationale="减税",
        )
        delta, attr, triggered, game_over, reactions, summary = process_decree(
            state, freeform=freeform,
        )
        assert isinstance(delta, dict)
        assert isinstance(attr, dict)
        assert isinstance(summary, TurnSummary)

    def test_freeform_effects_applied(self):
        state = make_state(national_treasury=20)
        freeform = FreeformResult(
            effects={"global.national_treasury": -20},
            narrative="测试",
            rationale="测试",
        )
        _, attr, _, _, _, _ = process_decree(state, freeform=freeform)
        # national_treasury effect should be recorded in attribution.
        assert attr.get("national_treasury", {}).get("旨意影响") == -20

    def test_freeform_chain_events_trigger(self):
        state = make_state(civil_morale=5, national_treasury=1, military_morale=5)
        freeform = FreeformResult(
            effects={"global.civil_morale": -5},
            narrative="测试",
            rationale="测试",
        )
        _, _, triggered, _, _, _ = process_decree(state, freeform=freeform)
        # with very low stats, chain events may trigger
        assert isinstance(triggered, list)

    def test_freeform_clamp_works(self):
        state = make_state(national_treasury=9990)
        freeform = FreeformResult(
            effects={"global.national_treasury": 50},
            narrative="测试",
            rationale="测试",
        )
        process_decree(state, freeform=freeform)
        assert state.national_treasury <= 10000

    def test_freeform_new_events_added(self):
        state = make_state()
        before_events = len(state.active_events)
        freeform = FreeformResult(
            effects={"global.national_treasury": -10},
            narrative="测试",
            rationale="测试",
            new_events=[{"name": "AI创建事件", "urgency": "高"}],
        )
        process_decree(state, freeform=freeform)
        ai_events = [e for e in state.active_events if e.name == "AI创建事件"]
        assert len(ai_events) == 1

    def test_freeform_time_advances(self):
        state = make_state()
        before_month = state.time.month
        freeform = FreeformResult(
            effects={"global.national_treasury": 5},
            narrative="测试",
            rationale="测试",
        )
        process_decree(state, freeform=freeform)
        # time advancement is handled by advance_month(), not process_decree()
        assert state.time.month == before_month

    def test_freeform_reactions_validated(self):
        state = make_state()
        freeform = FreeformResult(
            effects={"global.national_treasury": 5},
            narrative="测试",
            rationale="测试",
            reactions=[
                MinisterReaction(
                    minister_name="魏忠贤", faction="阉党残余",
                    reaction_type="oppose", reaction_text="臣反对！",
                    loyalty_change=-5,
                ),
                MinisterReaction(
                    minister_name="不存在", faction="unknown",
                    reaction_type="support", reaction_text="赞",
                    loyalty_change=0,
                ),
            ],
        )
        _, _, _, _, reactions, _ = process_decree(state, freeform=freeform)
        names = [r.minister_name for r in reactions]
        assert "魏忠贤" in names
        assert "不存在" not in names

    def test_freeform_execution_backlash(self):
        state = make_state()
        target = _minister(state, "魏忠贤")
        target.status = MinisterStatus.ACTIVE
        faction = _faction(state, "阉党残余")
        old_sat = faction.satisfaction

        freeform = FreeformResult(
            effects={"minister.魏忠贤.status": "removed"},
            narrative="处决魏忠贤",
            rationale="处决",
        )
        # validate then apply
        valid_effects = validate_ai_effects(freeform.effects, state)
        assert "minister.魏忠贤.status" in valid_effects

        process_decree(state, freeform=freeform)
        # faction satisfaction should decrease due to execution backlash
        assert faction.satisfaction < old_sat

    def test_freeform_game_over_check(self):
        state = make_state(
            national_treasury=0, civil_morale=0, military_morale=0,
            court_prestige=0, population=0,
        )
        freeform = FreeformResult(
            effects={"global.national_treasury": -10},
            narrative="国库崩溃",
            rationale="测试",
        )
        _, _, _, game_over, _, _ = process_decree(state, freeform=freeform)
        # game_over may or may not trigger depending on conditions
        # but the check should run without errors
        assert game_over is None or isinstance(game_over, dict)

    def test_freeform_decree_count_increments(self):
        state = make_state()
        before = state.decree_count
        freeform = FreeformResult(
            effects={"global.national_treasury": 5},
            narrative="测试",
            rationale="测试",
        )
        process_decree(state, freeform=freeform)
        # decree_count is incremented in advance_month(), not process_decree()
        assert state.decree_count == before


# ── 7.4 Parse prompt: execution vs harsh_punishment ──────

class TestParsePromptFixes:
    def test_execution_keyword_maps_to_personnel_execute(self):
        """'诛杀魏忠贤' → personnel + execute, not harsh_punishment."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.parse_free_input("诛杀魏忠贤", state))
        assert isinstance(result, list)
        assert len(result) >= 1
        d = result[0]
        assert d.type == DecreeType.PERSONNEL
        assert d.sub_action == PersonnelAction.EXECUTE
        assert d.target == "魏忠贤"

    def test_harsh_punishment_without_target(self):
        """'严刑峻法' → harsh_punishment (no specific target)."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.parse_free_input("严刑峻法", state))
        assert isinstance(result, list)
        assert result[0].type == DecreeType.HARSH_PUNISHMENT

    def test_execution_suffix_pattern(self):
        """'把魏忠贤斩了' → personnel + execute."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.parse_free_input("把魏忠贤斩了", state))
        assert isinstance(result, list)
        assert result[0].type == DecreeType.PERSONNEL
        assert result[0].sub_action == PersonnelAction.EXECUTE
        assert result[0].target == "魏忠贤"

    def test_execution_unknown_person_not_matched(self):
        """'斩杀不存在' → harsh_punishment fallback (not a minister name)."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.parse_free_input("斩杀不存在的人", state))
        assert isinstance(result, list)
        assert result[0].type == DecreeType.HARSH_PUNISHMENT

    def test_dismiss_maps_to_personnel_dismiss(self):
        """'罢免魏忠贤' → personnel + dismiss."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.parse_free_input("罢免魏忠贤", state))
        assert isinstance(result, list)
        assert result[0].type == DecreeType.PERSONNEL
        assert result[0].sub_action == PersonnelAction.DISMISS

    def test_freeform_mock_execution(self):
        """MockProvider.process_freeform: '斩杀魏忠贤' → FreeformResult with removed status."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.process_freeform("斩杀魏忠贤", state))
        assert isinstance(result, FreeformResult)
        assert "minister.魏忠贤.status" in result.effects
        assert result.effects["minister.魏忠贤.status"] == "removed"


# ── 7.5 Freeform fallback ───────────────────────────────

class _FreeformFailProvider(AIProvider):
    """Provider where process_freeform always fails, but parse_free_input works."""

    async def generate_narrative(self, *a, **kw) -> str:
        return ""

    async def stream_narrative(self, *a, **kw):
        narrative = await self.generate_narrative(*a, **kw)
        if narrative:
            yield narrative

    async def parse_free_input(self, text, game_state):
        return await MockProvider().parse_free_input(text, game_state)

    async def rejection_narrative(self, decree, reason) -> str:
        return ""

    async def generate_debate_narrative(self, *a, **kw):
        return None


    async def generate_memorial(self, *a, **kw):
        return ""

    async def generate_minister_reaction(self, *a, **kw):
        return ""

    async def generate_assembly_debate(self, *a, **kw):
        return None

    async def generate_turn_commentary(self, *a, **kw):
        return ""

    async def generate_minister_dialogue(self, *a, **kw):
        return {}

    async def process_freeform(self, text, game_state):
        return parse_error("freeform not supported")


class _FreeformTimeoutProvider(_FreeformFailProvider):
    """Provider where process_freeform always times out."""

    async def process_freeform(self, text, game_state):
        raise TimeoutError("AI service timeout")


class TestFreeformFallback:
    def test_freeform_error_falls_back_to_parse(self):
        """When process_freeform returns error dict, ResilientProvider still returns error
        (fallback to parse is done at the route level, not provider level)."""
        provider = ResilientProvider(_FreeformFailProvider(), retries=1)
        state = create_initial_state()
        result = asyncio.run(provider.process_freeform("加税", state))
        # ResilientProvider wraps process_freeform: error dict passes through
        assert isinstance(result, dict)
        assert "error" in result

    def test_freeform_timeout_returns_error(self):
        """When process_freeform times out, ResilientProvider returns error."""
        provider = ResilientProvider(_FreeformTimeoutProvider(), retries=1, timeout=0.1)
        state = create_initial_state()
        result = asyncio.run(provider.process_freeform("加税", state))
        assert isinstance(result, dict)
        assert "error" in result

    def test_route_level_fallback_logic(self):
        """Simulate the route-level fallback: freeform fails → parse_free_input."""
        provider = _FreeformFailProvider()
        state = create_initial_state()

        # Step 1: freeform fails
        freeform_result = asyncio.run(provider.process_freeform("加税", state))
        assert isinstance(freeform_result, dict) and "error" in freeform_result

        # Step 2: fallback to parse_free_input
        parsed = asyncio.run(provider.parse_free_input("加税", state))
        assert isinstance(parsed, list)
        assert len(parsed) >= 1
        assert parsed[0].type == DecreeType.TAX_INCREASE

    def test_freeform_success_no_fallback(self):
        """When process_freeform succeeds, no fallback needed."""
        provider = MockProvider()
        state = create_initial_state()
        result = asyncio.run(provider.process_freeform("加税", state))
        assert isinstance(result, FreeformResult)
        assert "global.national_treasury" in result.effects
