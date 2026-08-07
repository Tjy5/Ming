"""阶段B（跑团引擎）测试：检定/成长/修正/篇章/GM/API/持久化。"""
import asyncio
import json

import pytest

from ai.provider import ResilientProvider
from fakes import FakeProvider
from api import state as api_state
from api import trpg as trpg_routes
from db import saves as db_saves
from db.saves import IncompatibleSaveError, _migrate_save, load_game
from models.game import GameState, create_initial_state
from models.trpg import (
    ATTR_KEYS,
    PLAYER_NAME,
    ActRequest,
    CharacterSheet,
    TIER_CRITICAL_FAILURE,
    TIER_CRITICAL_SUCCESS,
    TIER_FAILURE,
    TIER_SUCCESS,
)
from trpg import chapter, character, dice, gm, modifiers


@pytest.fixture(autouse=True)
def _restore_globals():
    old_state = api_state._state
    old_provider = api_state._provider
    try:
        yield
    finally:
        api_state._state = old_state
        api_state._provider = old_provider
        dice.set_seed(None)


def _fake_provider():
    return ResilientProvider(FakeProvider(), timeout=1, retries=1)


def _fresh_sheet(**attrs_overrides) -> CharacterSheet:
    attrs = {"政治": 50, "军事": 50, "学识": 50, "交际": 50, "体力": 50, "胆略": 50}
    attrs.update(attrs_overrides)
    return CharacterSheet(name="测试", attrs=attrs)


# ── 1. D100 检定：DC / 目标值 / 分级边界 ─────────────────

class TestDice:
    def test_roll_in_range(self):
        for _ in range(200):
            assert 1 <= dice.roll_d100() <= 100

    def test_seed_reproducible(self):
        try:
            dice.set_seed(42)
            first = [dice.roll_d100() for _ in range(5)]
            dice.set_seed(42)
            second = [dice.roll_d100() for _ in range(5)]
            assert first == second
        finally:
            dice.set_seed(None)

    def test_dc_modifiers(self):
        assert dice.dc_modifier("简易") == 20
        assert dice.dc_modifier("常规") == 0
        assert dice.dc_modifier("困难") == -20
        assert dice.dc_modifier("极难") == -40
        assert dice.dc_modifier("easy") == 20
        assert dice.dc_modifier("extreme") == -40
        assert dice.dc_modifier("未知难度") == 0

    def test_chapter_default_difficulty_curve(self):
        """篇章 DC 曲线（阶段D 4.1）：childhood 简易 → warlord 极难；未知章兜底常规。"""
        assert dice.chapter_default_difficulty("childhood") == "简易"
        assert dice.chapter_default_difficulty("monk_wanderer") == "常规"
        assert dice.chapter_default_difficulty("enlistment") == "困难"
        assert dice.chapter_default_difficulty("warlord") == "极难"
        assert dice.chapter_default_difficulty("未知章") == "常规"
        assert dice.chapter_default_difficulty(None) == "常规"

    def test_target_without_skill_is_attr_half(self):
        sheet = _fresh_sheet(军事=51)
        assert dice.compute_target(sheet, "军事") == 25  # 51//2
        assert dice.compute_target(sheet, "军事", None, "简易") == 45
        assert dice.compute_target(sheet, "军事", None, "极难") == 1  # 25-40 触底 clamp

    def test_target_with_skill(self):
        sheet = _fresh_sheet(军事=50)
        sheet.skills["治军"] = 30
        assert dice.compute_target(sheet, "军事", "治军") == 25 + 15

    def test_target_ignores_unknown_skill(self):
        sheet = _fresh_sheet(军事=50)
        assert dice.compute_target(sheet, "军事", "不存在的技能") == 25

    def test_target_clamped_to_1_100(self):
        low = _fresh_sheet(军事=1)
        assert dice.compute_target(low, "军事", None, "极难") == 1
        high = _fresh_sheet(军事=100)
        high.skills["治军"] = 100
        assert dice.compute_target(high, "军事", "治军", "简易") == 100

    def test_tier_critical_success_boundaries(self):
        assert dice.classify_tier(1, 50) == TIER_CRITICAL_SUCCESS
        assert dice.classify_tier(5, 50) == TIER_CRITICAL_SUCCESS
        assert dice.classify_tier(6, 50) == TIER_SUCCESS

    def test_tier_critical_failure_boundaries(self):
        assert dice.classify_tier(96, 50) == TIER_CRITICAL_FAILURE
        assert dice.classify_tier(100, 50) == TIER_CRITICAL_FAILURE
        assert dice.classify_tier(95, 50) == TIER_FAILURE

    def test_tier_target_boundary(self):
        assert dice.classify_tier(50, 50) == TIER_SUCCESS      # 等于目标值=成功
        assert dice.classify_tier(51, 50) == TIER_FAILURE      # 目标值+1=失败
        assert dice.classify_tier(49, 50) == TIER_SUCCESS

    def test_tier_critical_priority_over_target(self):
        # roll=1 即使目标值极低也是大成功；roll=100 即使目标值满值也是大失败
        assert dice.classify_tier(1, 1) == TIER_CRITICAL_SUCCESS
        assert dice.classify_tier(100, 100) == TIER_CRITICAL_FAILURE
        assert dice.classify_tier(96, 99) == TIER_CRITICAL_FAILURE

    def test_perform_check_with_seed(self):
        sheet = _fresh_sheet()
        try:
            dice.set_seed(7)
            r1 = dice.perform_check(sheet, "军事", None, "常规")
            dice.set_seed(7)
            r2 = dice.perform_check(sheet, "军事", None, "常规")
            assert r1 == r2
            assert 1 <= r1.roll <= 100
            assert r1.dc == 0
            assert r1.attr_name == "军事"
        finally:
            dice.set_seed(None)


# ── 2. 角色卡与成长 ──────────────────────────────────────

class TestCharacter:
    def test_player_initial_sheet(self):
        sheet = character.create_player_sheet()
        assert sheet.name == PLAYER_NAME
        assert sheet.is_player
        assert set(sheet.attrs.keys()) == set(ATTR_KEYS)
        for value in sheet.attrs.values():
            assert 40 <= value <= 55  # 初始主属性 40-55

    def test_attrs_range_validation(self):
        with pytest.raises(ValueError):
            CharacterSheet(name="x", attrs={"政治": 101})
        with pytest.raises(ValueError):
            CharacterSheet(name="x", attrs={"政治": -1})

    def test_ensure_sheets_builds_player_and_key_figures(self):
        state = create_initial_state()
        sheets = character.ensure_sheets(state)
        assert PLAYER_NAME in sheets
        assert "徐达" in sheets
        assert sheets[PLAYER_NAME].is_player
        assert not sheets["徐达"].is_player
        # 惰性：二次调用不重建
        assert character.ensure_sheets(state) is sheets

    def test_key_figure_sheets_deterministic(self):
        a = character.build_initial_sheets()
        b = character.build_initial_sheets()
        assert a == b

    def test_growth_conversion_every_five_points(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        sheet = character.get_sheet(state, PLAYER_NAME)
        before = sheet.attrs["军事"]
        entry = character.award_skill_points(state, PLAYER_NAME, 5, "测试", "军事")
        assert entry is not None
        assert entry.growth_points == 1
        assert entry.attr_gain == 1
        assert sheet.attrs["军事"] == before + 1
        assert sheet.growth_points == 0  # 折算的成长点已全部投入属性

    def test_growth_remainder_accumulates(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        sheet = character.get_sheet(state, PLAYER_NAME)
        e1 = character.award_skill_points(state, PLAYER_NAME, 2, "测试", "军事")
        assert e1.growth_points == 0 and e1.attr_gain == 0
        e2 = character.award_skill_points(state, PLAYER_NAME, 3, "测试", "军事")
        assert e2.growth_points == 1 and e2.attr_gain == 1
        assert sheet.skill_points == 0

    def test_growth_attr_cap_100(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        sheet = character.get_sheet(state, PLAYER_NAME)
        sheet.attrs["军事"] = 99
        entry = character.award_skill_points(state, PLAYER_NAME, 10, "测试", "军事")
        assert entry.attr_gain == 1          # 只能再涨 1 点
        assert sheet.attrs["军事"] == 100
        assert sheet.growth_points == 1      # 剩余成长点留存
        assert not character.spend_growth_point(sheet, "军事")  # 满属性不可再投

    def test_spend_growth_point(self):
        sheet = character.create_player_sheet()
        sheet.growth_points = 2
        before = sheet.attrs["政治"]
        assert character.spend_growth_point(sheet, "政治")
        assert sheet.attrs["政治"] == before + 1
        assert sheet.growth_points == 1
        assert character.spend_growth_point(sheet, "政治")
        assert not character.spend_growth_point(sheet, "政治")  # 成长点耗尽
        assert not character.spend_growth_point(_fresh_sheet(), "政治")  # 无成长点

    def test_narrative_turn_points_contract(self):
        assert character.narrative_turn_points(TIER_SUCCESS) == 2
        assert character.narrative_turn_points(TIER_CRITICAL_SUCCESS) == 2
        assert character.narrative_turn_points(TIER_FAILURE) == 1
        assert character.narrative_turn_points(TIER_CRITICAL_FAILURE) == 1

    def test_key_event_awards_extra_points(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        state.chapter = "childhood"
        result = character.complete_key_event_with_growth(state, "birth-1328")
        assert result is not None
        assert result["growth"]["skill_points"] == character.KEY_EVENT_POINTS
        assert any("关键事件" in e.source for e in state.growth_log)

    def test_growth_chain_conversion_locked(self):
        """成长链锁定（阶段D 4.2 校准基线）：技能点 → 成长点 → 属性投入 5:1。

        10 成功回合（20 技能点）→ 4 成长点全部投入检定属性（+4）；
        关键事件奖励（attr_name=None）仅折算成长点暂存，不自动投入属性
        （由后续检定折算投入）。常量调整需回归此链路（e2e 属性断言复验归步骤 7）。
        """
        state = create_initial_state()
        character.ensure_sheets(state)
        sheet = state.character_sheets[PLAYER_NAME]
        before = sheet.attrs["军事"]
        for _ in range(10):
            character.award_skill_points(state, PLAYER_NAME, 2, "叙事回合", "军事")
        character.complete_key_event_with_growth(state, "birth-1328")
        character.complete_key_event_with_growth(state, "famine-1344")
        assert sheet.attrs["军事"] == before + 4
        assert sheet.skill_points == 1          # 关键事件 6 点折算后余 1
        assert sheet.growth_points == 1         # 折算的成长点暂存待投入


# ── 3. 治理修正契约（本阶段不接入引擎）────────────────────

class TestModifiers:
    def test_success_mod_formula_and_cap(self):
        assert modifiers.success_mod(50) == 0.0
        assert modifiers.success_mod(75) == pytest.approx(0.25)
        assert modifiers.success_mod(25) == pytest.approx(-0.25)
        assert modifiers.success_mod(100) == 0.5
        assert modifiers.success_mod(0) == -0.5

    def test_player_modifiers_mapping(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        mods = modifiers.get_player_modifiers(state)
        assert set(mods.keys()) == {"military", "domestic", "diplomacy", "culture"}
        sheet = state.character_sheets[PLAYER_NAME]
        assert mods["military"] == modifiers.success_mod(sheet.attrs["军事"])
        assert mods["domestic"] == modifiers.success_mod(sheet.attrs["政治"])
        assert mods["diplomacy"] == modifiers.success_mod(sheet.attrs["交际"])
        assert mods["culture"] == modifiers.success_mod(sheet.attrs["学识"])

    def test_no_player_sheet_returns_empty(self):
        state = create_initial_state()
        assert modifiers.get_player_modifiers(state) == {}


# ── 4. 人生篇章推进 ──────────────────────────────────────

class TestChapter:
    def test_chapters_loaded(self):
        ids = [c["id"] for c in chapter.get_chapters()]
        assert ids == ["childhood", "monk_wanderer", "enlistment", "warlord"]
        assert chapter.chapter_title("childhood") == "农家子"

    def test_advance_chapter_jumps_year(self):
        state = create_initial_state()
        state.chapter = "childhood"
        state.chapter_turns = 4
        result = chapter.advance_chapter(state)
        assert result["to_chapter"] == "monk_wanderer"
        assert state.chapter == "monk_wanderer"
        assert state.time.year == 1344
        assert state.time.month == 1
        assert state.chapter_turns == 0
        assert result["summary"]

    def test_advance_frozen_in_governance(self):
        state = create_initial_state()
        state.phase = "governance"
        assert chapter.is_frozen(state)
        assert chapter.advance_chapter(state) is None
        assert state.chapter == "childhood"

    def test_advance_last_chapter_returns_none(self):
        state = create_initial_state()
        state.chapter = "warlord"
        assert chapter.advance_chapter(state) is None

    def test_complete_key_event_marks_milestone(self):
        state = create_initial_state()
        result = chapter.complete_key_event(state, "birth-1328")
        assert result["milestone"] == "birth-1328"
        assert "birth-1328" in state.resolved_script_ids
        assert result["transition"] is None  # 非章末里程碑不切章

    def test_last_chapter_event_triggers_transition(self):
        state = create_initial_state()
        state.chapter = "childhood"
        result = chapter.complete_key_event(state, "famine-1344")
        assert result["transition"] is not None
        assert state.chapter == "monk_wanderer"
        assert state.time.year == 1344

    def test_yingtian_founding_phase_switch_flag(self):
        state = create_initial_state()
        state.chapter = "warlord"
        result = chapter.complete_key_event(state, "yingtian-founding")
        assert result["phase_switch"] is True   # 供阶段D触发切换
        assert state.phase == "life_story"      # 本阶段不改 phase
        assert result["transition"] is None     # 非 warlord 末里程碑

    def test_unknown_milestone_returns_none(self):
        state = create_initial_state()
        assert chapter.complete_key_event(state, "不存在") is None

    def test_record_turn_and_pacing(self):
        state = create_initial_state()
        assert chapter.record_turn(state) == 1
        assert chapter.record_turn(state) == 2
        assert state.chapter_turns == 2
        pacing = chapter.pacing_status(2)
        assert not pacing["may_advance"]
        assert chapter.pacing_status(3)["may_advance"]
        assert chapter.pacing_status(8)["must_advance"]

    def test_convergence_hook_after_fallback_year(self):
        state = create_initial_state()
        state.time.year = 1360
        hook = chapter.check_convergence_hook(state)
        assert hook is not None
        assert hook["hook"] == "convergence"
        assert hook["milestone"] == "yingtian-founding"
        assert hook["fallback_year"] == 1360

    def test_convergence_hook_none_cases(self):
        state = create_initial_state()
        assert chapter.check_convergence_hook(state) is None  # 1328 < 1360
        state.time.year = 1361
        state.resolved_script_ids.add("yingtian-founding")
        assert chapter.check_convergence_hook(state) is None  # 已完成
        state.resolved_script_ids.discard("yingtian-founding")
        state.phase = "governance"
        assert chapter.check_convergence_hook(state) is None  # 冻结


# ── 5. AI 主持人（GM）────────────────────────────────────

def _gm_roll(tier: str) -> "object":
    from models.trpg import RollResult
    return RollResult(roll=30, target=50, tier=tier, dc=0, attr_name="军事")


def _gm_context(tier: str) -> dict:
    state = create_initial_state()
    sheet = character.create_player_sheet()
    return gm.build_context(
        state=state,
        sheet=sheet,
        action_text="夜袭元军粮营",
        roll=_gm_roll(tier),
        chapter_title="农家子",
    )


class _FakeProvider:
    def __init__(self, response: str):
        self._response = response

    async def chat_query(self, text, game_state, history):
        return self._response


class _RaisingProvider:
    async def chat_query(self, text, game_state, history):
        raise RuntimeError("ai offline")


class TestGM:
    def test_rule_narrative_deterministic(self):
        ctx = _gm_context(TIER_SUCCESS)
        a = gm.rule_based_narrative(ctx)
        b = gm.rule_based_narrative(ctx)
        assert a == b
        assert a["source"] == "rule"
        assert a["state_changes"] == {}
        assert a["narrative"]

    def test_rule_options_stable_ids_and_counts(self):
        success = gm.rule_based_narrative(_gm_context(TIER_SUCCESS))
        assert len(success["options"]) == 3
        assert [o["option_id"] for o in success["options"]] == [
            "opt_press_ahead", "opt_secure_gains", "opt_observe",
        ]
        critical = gm.rule_based_narrative(_gm_context(TIER_CRITICAL_SUCCESS))
        assert len(critical["options"]) == 4
        assert critical["options"][-1]["option_id"] == "opt_bold_expand"
        failure = gm.rule_based_narrative(_gm_context(TIER_CRITICAL_FAILURE))
        assert len(failure["options"]) == 4
        assert failure["options"][-1]["option_id"] == "opt_cut_losses"

    def test_parse_valid_response(self):
        raw = json.dumps({
            "narrative": "夜色如墨，行动得手。",
            "options": [
                {"option_id": "a", "label": "甲"},
                {"label": "乙"},
                {"option_id": "c", "label": "丙", "description": "说明"},
            ],
            "state_changes": {"civil_morale": 1},
        }, ensure_ascii=False)
        parsed = gm.parse_gm_response(raw)
        assert parsed is not None
        assert parsed["options"][1]["option_id"] == "opt_ai_2"  # 缺省补稳定ID
        assert parsed["state_changes"] == {"civil_morale": 1}

    def test_parse_invalid_responses(self):
        assert gm.parse_gm_response("这不是JSON") is None
        assert gm.parse_gm_response(None) is None
        assert gm.parse_gm_response('{"narrative": ""}') is None
        # 选项少于3个不合规
        too_few = json.dumps({
            "narrative": "n",
            "options": [{"label": "a"}, {"label": "b"}],
        })
        assert gm.parse_gm_response(too_few) is None

    def test_parse_keeps_optional_milestone_id(self):
        """AI 选项可携带 milestone_id（前端据此调 complete 端点而非 /act）。"""
        raw = json.dumps({
            "narrative": "天时已至。",
            "options": [
                {"option_id": "o1", "label": "完成关键事件", "description": "x",
                 "milestone_id": "famine-1344"},
                {"option_id": "o2", "label": "乙"},
                {"option_id": "o3", "label": "丙"},
            ],
        }, ensure_ascii=False)
        parsed = gm.parse_gm_response(raw)
        assert parsed is not None
        assert parsed["options"][0]["milestone_id"] == "famine-1344"
        assert "milestone_id" not in parsed["options"][1]  # 无该字段的选项不带出

    def test_generate_turn_provider_none_falls_back(self):
        state = create_initial_state()
        result = asyncio.run(gm.generate_turn(
            None,
            state=state,
            sheet=character.create_player_sheet(),
            action_text="试探",
            roll=_gm_roll(TIER_FAILURE),
            chapter_title="农家子",
        ))
        assert result["source"] == "rule"

    def test_generate_turn_ai_success(self):
        payload = json.dumps({
            "narrative": "AI叙事",
            "options": [{"label": "一"}, {"label": "二"}, {"label": "三"}],
            "state_changes": {},
        }, ensure_ascii=False)
        result = asyncio.run(gm.generate_turn(
            _FakeProvider(payload),
            state=create_initial_state(),
            sheet=character.create_player_sheet(),
            action_text="试探",
            roll=_gm_roll(TIER_SUCCESS),
            chapter_title="农家子",
        ))
        assert result["source"] == "ai"
        assert result["narrative"] == "AI叙事"

    def test_generate_turn_ai_error_falls_back(self):
        result = asyncio.run(gm.generate_turn(
            _RaisingProvider(),
            state=create_initial_state(),
            sheet=character.create_player_sheet(),
            action_text="试探",
            roll=_gm_roll(TIER_SUCCESS),
            chapter_title="农家子",
        ))
        assert result["source"] == "rule"

    def test_generate_turn_unparseable_ai_falls_back(self):
        result = asyncio.run(gm.generate_turn(
            _fake_provider(),  # FakeProvider 返回非 JSON → 解析失败 → 规则回退
            state=create_initial_state(),
            sheet=character.create_player_sheet(),
            action_text="试探",
            roll=_gm_roll(TIER_SUCCESS),
            chapter_title="农家子",
        ))
        assert result["source"] == "rule"


# ── 6. API：角色卡 / 行动检定 ────────────────────────────

class TestApi:
    def test_get_character(self):
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.get_character())
        assert resp["player"]["name"] == PLAYER_NAME
        assert set(resp["player"]["attrs"].keys()) == set(ATTR_KEYS)
        assert resp["phase"] == "life_story"
        assert resp["chapter"] == "childhood"
        names = {f["name"] for f in resp["key_figures"]}
        assert "徐达" in names
        assert PLAYER_NAME not in names

    def test_act_happy_path_with_rule_fallback(self):
        api_state._provider = _fake_provider()
        api_state._state = create_initial_state()
        req = ActRequest(action_text="夜巡大营，整肃军纪", skill="治军")
        resp = asyncio.run(trpg_routes.act(req))

        assert resp["source"] == "rule"  # Mock 输出非 JSON → 确定性规则回退
        assert 1 <= resp["roll"]["roll"] <= 100
        assert resp["roll"]["attr_name"] == "军事"   # 治军 → 军事
        assert resp["roll"]["skill_name"] == "治军"
        assert 3 <= len(resp["options"]) <= 4
        assert resp["chapter_turns"] == 1
        assert resp["growth"] is not None
        assert resp["growth"]["skill_points"] in (1, 2)
        state = api_state._state
        assert state.chapter_turns == 1
        assert state.history_log[-1].decree_type == "trpg_act"
        assert len(state.growth_log) == 1

    def test_act_deterministic_with_same_seed(self):
        api_state._provider = _fake_provider()
        req = ActRequest(action_text="暗访濠州城中元军虚实")

        api_state._state = create_initial_state()
        dice.set_seed(2026)
        first = asyncio.run(trpg_routes.act(req))

        api_state._state = create_initial_state()
        dice.set_seed(2026)
        second = asyncio.run(trpg_routes.act(req))

        assert first == second  # 同输入同输出（骰子+规则回退全确定性）

    def test_act_explicit_attr_and_default(self):
        api_state._provider = _fake_provider()
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.act(
            ActRequest(action_text="修书一封", attr="学识"),
        ))
        assert resp["roll"]["attr_name"] == "学识"

        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.act(
            ActRequest(action_text="纵马跃涧", skill="未收录的技能"),
        ))
        assert resp["roll"]["attr_name"] == "胆略"  # 兜底属性

    def test_act_difficulty_modifies_target(self):
        api_state._provider = _fake_provider()
        # 显式难度尊重原值（用 monk_wanderer 章：其默认难度即"常规"，排除曲线干扰）
        def _state():
            s = create_initial_state()
            s.chapter = "monk_wanderer"
            return s

        api_state._state = _state()
        easy = asyncio.run(trpg_routes.act(
            ActRequest(action_text="挑水劈柴", attr="体力", difficulty="简易"),
        ))
        api_state._state = _state()
        normal = asyncio.run(trpg_routes.act(
            ActRequest(action_text="挑水劈柴", attr="体力", difficulty="常规"),
        ))
        api_state._state = _state()
        extreme = asyncio.run(trpg_routes.act(
            ActRequest(action_text="挑水劈柴", attr="体力", difficulty="极难"),
        ))
        assert easy["roll"]["dc"] == 20
        assert normal["roll"]["dc"] == 0
        assert extreme["roll"]["dc"] == -40
        # 体力55 → 基础 27：简易 47、常规 27、极难 -13 触底 clamp 为 1
        assert easy["roll"]["target"] - normal["roll"]["target"] == 20
        assert extreme["roll"]["target"] == 1

    def test_act_echoes_option_id(self):
        """option_id（design 第 5.1 节）：确定性选择双通道，随响应回显；不匹配忽略不报错。"""
        api_state._provider = _fake_provider()
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.act(ActRequest(
            action_text="夜巡大营", option_id="opt_secure_gains",
        )))
        assert resp["option_id"] == "opt_secure_gains"
        # 不传 option_id → null（向后兼容）
        api_state._state = create_initial_state()
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="夜巡大营")))
        assert resp["option_id"] is None

    def test_act_chapter_default_difficulty_curve(self):
        """/act 未显式指定难度 → 按当前章默认（篇章 DC 曲线）；显式指定不被覆盖。"""
        api_state._provider = _fake_provider()

        api_state._state = create_initial_state()   # childhood → 简易
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="挑水劈柴", attr="体力")))
        assert resp["roll"]["dc"] == 20

        state = create_initial_state()
        state.chapter = "enlistment"                # 投军 → 困难
        api_state._state = state
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="夜探敌营", attr="胆略")))
        assert resp["roll"]["dc"] == -20

        api_state._state = create_initial_state()   # childhood 内显式"极难"不被覆盖
        resp = asyncio.run(trpg_routes.act(
            ActRequest(action_text="纵马越涧", attr="体力", difficulty="极难"),
        ))
        assert resp["roll"]["dc"] == -40

        state = create_initial_state()
        state.chapter = "神秘篇章"                   # 未知章兜底"常规"
        api_state._state = state
        resp = asyncio.run(trpg_routes.act(ActRequest(action_text="四方打听", attr="交际")))
        assert resp["roll"]["dc"] == 0

    def test_act_in_governance_phase_is_auxiliary(self):
        api_state._provider = _fake_provider()
        state = create_initial_state()
        state.phase = "governance"
        api_state._state = state
        resp = asyncio.run(trpg_routes.act(
            ActRequest(action_text="治理阶段的辅助检定"),
        ))
        assert resp["frozen"] is True
        assert resp["chapter_turns"] == 0        # 篇章冻结不计回合
        assert api_state._state.chapter_turns == 0
        assert resp["convergence_hook"] is None
        assert resp["narrative"]                 # 检定与叙事仍可用


# ── 7. 持久化：存档往返 / 迁移 / 不兼容 ──────────────────

class TestPersistence:
    def test_save_roundtrip_preserves_sheets(self):
        state = create_initial_state()
        character.ensure_sheets(state)
        character.award_skill_points(state, PLAYER_NAME, 5, "叙事回合", "军事")
        restored = GameState.model_validate_json(state.model_dump_json())
        assert restored.character_sheets == state.character_sheets
        assert restored.growth_log == state.growth_log
        assert restored.chapter == state.chapter == "childhood"
        assert restored.phase == "life_story"

    def test_migrate_backfills_trpg_fields_silently(self):
        from models.game import INITIAL_MINISTERS
        data = {
            "time": {"year": 1360, "month": 6, "era_name": "至正", "era_year": 20},
            "national_treasury": 50, "imperial_treasury": 30, "grain": 20,
            "population": 15000, "military_strength": 80,
            "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
            "factions": [], "active_events": [], "history_log": [],
            "decree_count": 5, "event_cooldowns": {}, "regions": [],
            "ministers": [m.model_dump() for m in INITIAL_MINISTERS],
            "phase": "governance",
            "resolved_script_ids": [],
        }
        notes = _migrate_save(data)
        assert notes == []                        # 静默回填，不产生迁移提示
        assert data["chapter"] == "childhood"
        assert data["chapter_turns"] == 0
        assert data["character_sheets"] == {}
        assert data["growth_log"] == []
        # 幂等
        snap = json.loads(json.dumps(data))
        _migrate_save(data)
        assert data == snap

    def test_load_game_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(db_saves, "DB_PATH", tmp_path / "saves.db")
        db_saves.init_db()
        state = create_initial_state()
        character.ensure_sheets(state)
        save_id = db_saves.save_game(state, "测试存档")
        loaded, migrated, note = load_game(save_id)
        assert loaded.phase == "life_story"
        assert loaded.chapter == "childhood"
        assert loaded.character_sheets == state.character_sheets
        assert not migrated and note == ""

    def test_load_game_rejects_chongzhen_save(self, monkeypatch, tmp_path):
        monkeypatch.setattr(db_saves, "DB_PATH", tmp_path / "saves.db")
        db_saves.init_db()
        old_save = json.dumps({
            "time": {"year": 1627, "month": 1, "era_name": "崇祯", "era_year": 1},
        }, ensure_ascii=False)
        with db_saves._connect() as conn:
            conn.execute(
                "INSERT INTO saves (name, game_time, created_at, state_json) VALUES (?, ?, ?, ?)",
                ("旧崇祯存档", "崇祯元年1月", "2026-01-01T00:00:00+00:00", old_save),
            )
        with pytest.raises(IncompatibleSaveError):
            load_game(1)
